from dotenv import load_dotenv
load_dotenv()
import discord
from discord import app_commands
import os
import asyncpg
import asyncio
import logging
import traceback
import re
import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nexusbot")

BOT_OWNER_ID = int(os.environ.get("BOT_OWNER_ID", "0"))
logger.info(f"BOT_OWNER_ID loaded: {BOT_OWNER_ID}")

DB_URL = os.environ.get("DATABASE_URL")
if DB_URL and DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

pool = None


async def init_db():
    global pool
    if not DB_URL:
        logger.error("DATABASE_URL is not set.")
        return
    try:
        try:
            pool = await asyncpg.create_pool(DB_URL, ssl='require')
            logger.info("Connected to database (SSL).")
        except Exception:
            pool = await asyncpg.create_pool(DB_URL)
            logger.info("Connected to database (no SSL).")
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_logs (
                    id SERIAL PRIMARY KEY,
                    level VARCHAR(10) NOT NULL DEFAULT 'info',
                    message TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id SERIAL PRIMARY KEY,
                    guild_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    ticket_type TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    channel_id TEXT,
                    claimer_id TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    claimed_at TIMESTAMP
                );
            """)
        logger.info("All database tables verified/created.")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")


async def log_to_db(level, message):
    if pool:
        try:
            await pool.execute(
                "INSERT INTO bot_logs (level, message) VALUES ($1, $2)",
                level, str(message)
            )
        except Exception as e:
            logger.error(f"Failed to log to DB: {e}")


intents = discord.Intents.default()
intents.members = True


class NexusBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.synced = False

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        await log_to_db('info', f'Bot logged in as {self.user}')

        try:
            self.add_view(AdminTicketPanelView())
            self.add_dynamic_items(ClaimAdminTicketButton, CloseAdminTicketButton)
            logger.info("Registered persistent admin ticket views.")
        except Exception as e:
            logger.error(f"Failed to register admin ticket views: {e}")

        if not self.synced:
            for guild in self.guilds:
                try:
                    self.tree.copy_global_to(guild=guild)
                    synced = await self.tree.sync(guild=guild)
                    logger.info(f"Synced {len(synced)} slash commands to {guild.name}")
                    await log_to_db('info', f'Synced {len(synced)} commands to {guild.name}')
                except Exception as e:
                    logger.error(f"Failed to sync to {guild.name}: {e}")
                    await log_to_db('error', f'Failed to sync to {guild.name}: {e}')
            self.synced = True

    async def on_guild_join(self, guild):
        try:
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
            except Exception:
                pass
        except Exception:
            logger.error(f"Error in on_guild_join: {traceback.format_exc()}")


bot = NexusBot()


async def is_bot_owner_or_server_owner(guild, user_id):
    if BOT_OWNER_ID and user_id == BOT_OWNER_ID:
        return True
    if guild.owner_id == user_id:
        return True
    return False


def make_short_name(member):
    raw = (getattr(member, 'display_name', None) or getattr(member, 'name', None) or str(member.id))
    name = raw.lower()
    name = re.sub(r'[^a-z0-9]', '', name)
    return name[:10] or str(member.id)[-4:]


ROLE_GERANT_RP = 1521523237383835718
ROLE_GERANT_STAFF = 1521523168659898573
ROLE_ADMINISTRATEUR = 1521523276315099309
ROLE_FULL_ACCESS_1 = 1521498188148768809
ROLE_FULL_ACCESS_2 = 1521523197764305130

ADMIN_CATEGORY_ID = 1521698472976453795

TICKET_LOG_CHANNEL_ID = 1521716387695820881
TICKET_LOG_CHANNEL = "logs・tickets-admin"
TICKET_LOG_CATEGORY = "Logs - TicketsAdmin"


ADMIN_TICKET_TYPES = {
    "trahison": {"label": "Ticket Trahison", "short": "trh", "emoji": "⚔️", "circle": "🔴"},
    "desertion": {"label": "Ticket Desertion", "short": "des", "emoji": "🏃", "circle": "🟠"},
    "naissance": {"label": "Ticket Naissance", "short": "nai", "emoji": "👶", "circle": "🟢"},
    "coup_etat": {"label": "Ticket Coup d'Etat", "short": "coup", "emoji": "👑", "circle": "🟣"},
    "vol": {"label": "Ticket Vol", "short": "vol", "emoji": "💰", "circle": "🟡"},
    "rpk_joueur": {"label": "Ticket RPK vers un joueur", "short": "rpk", "emoji": "🎯", "circle": "🟤"},
    "void": {"label": "Ticket VOID", "short": "void", "emoji": "🌀", "circle": "⚫"},
}

ADMIN_TICKET_ORDER = ["trahison", "desertion", "naissance", "coup_etat", "vol", "rpk_joueur", "void"]

ADMIN_TICKET_VIEW_ROLES_DEFAULT = [ROLE_GERANT_RP, ROLE_GERANT_STAFF, ROLE_FULL_ACCESS_1, ROLE_FULL_ACCESS_2]
ADMIN_TICKET_VIEW_ROLES_VOID = [ROLE_GERANT_RP, ROLE_GERANT_STAFF, ROLE_FULL_ACCESS_1, ROLE_FULL_ACCESS_2, ROLE_ADMINISTRATEUR]

ADMIN_TICKET_PING_ROLES_DEFAULT = [ROLE_GERANT_RP, ROLE_GERANT_STAFF]
ADMIN_TICKET_PING_ROLES_VOID = [ROLE_GERANT_RP, ROLE_GERANT_STAFF, ROLE_ADMINISTRATEUR]


def get_admin_ticket_view_roles(ticket_type_key: str):
    if ticket_type_key == "void":
        return ADMIN_TICKET_VIEW_ROLES_VOID
    return ADMIN_TICKET_VIEW_ROLES_DEFAULT


def get_admin_ticket_ping_roles(ticket_type_key: str):
    if ticket_type_key == "void":
        return ADMIN_TICKET_PING_ROLES_VOID
    return ADMIN_TICKET_PING_ROLES_DEFAULT


async def get_ticket_log_channel(guild):
    try:
        ch = guild.get_channel(TICKET_LOG_CHANNEL_ID)
        if ch:
            return ch
        cat = discord.utils.get(guild.categories, name=TICKET_LOG_CATEGORY)
        if cat:
            ch = discord.utils.get(cat.text_channels, name=TICKET_LOG_CHANNEL)
            if ch:
                return ch
        ch = discord.utils.get(guild.text_channels, name=TICKET_LOG_CHANNEL)
        return ch
    except Exception:
        return None


async def log_ticket_event(guild, event_type: str, ticket_id: int, ticket_type_key: str,
                            creator_id: str, channel=None, claimer_id: str = None,
                            closer=None, opened_at=None, claimed_at=None):
    try:
        log_ch = await get_ticket_log_channel(guild)
        if not log_ch:
            return

        ticket_info = ADMIN_TICKET_TYPES.get(ticket_type_key, {})
        type_label = f"{ticket_info.get('emoji', '🎫')} {ticket_info.get('label', ticket_type_key)}"

        if event_type == "open":
            title = "🟢 Ticket ouvert"
            color = 0x2ecc71
        elif event_type == "claim":
            title = "🟡 Ticket pris en charge"
            color = 0xf1c40f
        elif event_type == "close":
            title = "🔴 Ticket fermé"
            color = 0xed4245
        else:
            title = "Ticket"
            color = 0x2b2d31

        embed = discord.Embed(title=title, color=color, timestamp=datetime.datetime.utcnow())
        embed.add_field(name="Type", value=type_label, inline=True)
        embed.add_field(name="ID Ticket", value=f"`{ticket_id}`", inline=True)
        if channel is not None:
            try:
                embed.add_field(name="Salon", value=f"#{channel.name}", inline=True)
            except Exception:
                pass

        if creator_id:
            embed.add_field(name="Ouvert par", value=f"<@{creator_id}> (`{creator_id}`)", inline=False)

        if claimer_id:
            embed.add_field(name="Pris en charge par", value=f"<@{claimer_id}> (`{claimer_id}`)", inline=False)

        if closer is not None:
            embed.add_field(name="Fermé par", value=f"{closer.mention} (`{closer.id}`)", inline=False)

        if opened_at:
            try:
                ts = int(opened_at.timestamp())
                embed.add_field(name="Ouvert le", value=f"<t:{ts}:F>", inline=True)
            except Exception:
                pass
        if claimed_at:
            try:
                ts = int(claimed_at.timestamp())
                embed.add_field(name="Pris en charge le", value=f"<t:{ts}:F>", inline=True)
            except Exception:
                pass

        embed.set_footer(text="MssClick • Logs Tickets Admin")
        await log_ch.send(embed=embed)
    except Exception as e:
        logger.error(f"log_ticket_event error: {e}")


class AdminTicketSelect(discord.ui.Select):
    def __init__(self):
        options = []
        for k in ADMIN_TICKET_ORDER:
            t = ADMIN_TICKET_TYPES[k]
            options.append(discord.SelectOption(
                label=t["label"][:100],
                value=k,
                emoji=t.get("emoji"),
            ))
        super().__init__(
            placeholder="Sélectionnez votre raison...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="admin_ticket_panel_select",
        )

    async def callback(self, interaction: discord.Interaction):
        await handle_admin_ticket_creation(interaction, self.values[0])


class AdminTicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(AdminTicketSelect())


class TicketAdminLayout(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        container = discord.ui.Container(accent_colour=0x2b2d31)

        container.add_item(discord.ui.TextDisplay(
            "## 🎫  Ouvrir un ticket auprès de l'Administration"
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "### 📌 Comment ça marche ?\n"
            "1️⃣ Sélectionnez la **raison** de votre demande dans le menu ci-dessous.\n"
            "2️⃣ Le bot crée un ticket transmis à l'équipe concernée.\n"
            "3️⃣ Vous recevez un message privé dès qu'un membre du staff le prend en charge."
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "### 🤝 Règles de courtoisie\n"
            "• Restez poli et respectueux envers le staff.\n"
            "• Toute forme de harcèlement ou d'abus est strictement interdite."
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "### ⏳ Information importante\n"
            "» Pour les entretiens, les coups d'État ou les autorisations RP, merci de faire preuve de patience : les délais de réponse peuvent varier."
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "### 🎯 Sélection du ticket\n"
            "Choisissez une raison dans le menu ci-dessous pour commencer."
        ))

        action_row = discord.ui.ActionRow()
        action_row.add_item(AdminTicketSelect())
        container.add_item(action_row)

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "-# Orizon • Poudlard | Autorisation RP"
        ))

        self.add_item(container)


class ClaimAdminTicketButton(discord.ui.DynamicItem[discord.ui.Button], template=r'claim_admin:(?P<id>\d+)'):
    def __init__(self, ticket_id: int):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label='Claim',
                emoji='🎫',
                style=discord.ButtonStyle.green,
                custom_id=f'claim_admin:{ticket_id}',
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match['id']))

    async def callback(self, interaction: discord.Interaction):
        await handle_admin_claim(interaction, self.ticket_id)


class CloseAdminTicketButton(discord.ui.DynamicItem[discord.ui.Button], template=r'close_admin:(?P<id>\d+)'):
    def __init__(self, ticket_id: int):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label='Fermer le ticket',
                emoji='🔒',
                style=discord.ButtonStyle.danger,
                custom_id=f'close_admin:{ticket_id}',
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match['id']))

    async def callback(self, interaction: discord.Interaction):
        await handle_close_admin_ticket(interaction, self.ticket_id)


async def handle_admin_ticket_creation(interaction: discord.Interaction, ticket_type_key: str):
    try:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user = interaction.user

        if not guild:
            await interaction.followup.send("❌ Cette commande doit être utilisée sur un serveur.", ephemeral=True)
            return

        ticket_info = ADMIN_TICKET_TYPES.get(ticket_type_key)
        if not ticket_info:
            await interaction.followup.send("❌ Type de ticket inconnu.", ephemeral=True)
            return

        if not pool:
            await interaction.followup.send("❌ Base de données indisponible.", ephemeral=True)
            return

        existing = await pool.fetchrow(
            "SELECT id, status, channel_id FROM tickets WHERE guild_id = $1 AND user_id = $2 AND ticket_type = $3 AND status IN ('pending', 'open')",
            str(guild.id), str(user.id), ticket_type_key
        )
        if existing:
            ch_id = existing['channel_id']
            if ch_id:
                channel = guild.get_channel(int(ch_id))
                if channel:
                    await interaction.followup.send(
                        f"❌ Vous avez déjà un ticket de ce type ouvert : {channel.mention}",
                        ephemeral=True
                    )
                    return

        ticket_id = await pool.fetchval(
            "INSERT INTO tickets (guild_id, user_id, ticket_type, status) VALUES ($1, $2, $3, 'open') RETURNING id",
            str(guild.id), str(user.id), ticket_type_key
        )

        category = guild.get_channel(ADMIN_CATEGORY_ID)
        if not category or not isinstance(category, discord.CategoryChannel):
            await interaction.followup.send("❌ Catégorie de tickets introuvable. Contactez un administrateur.", ephemeral=True)
            return

        creator_short = make_short_name(user)
        channel_name = f"{ticket_info.get('circle','')}{ticket_info['short']}-{creator_short}"

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                read_message_history=True, manage_channels=True, manage_messages=True
            ),
            user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                read_message_history=True, attach_files=True, embed_links=True
            ),
        }
        for role_id in get_admin_ticket_view_roles(ticket_type_key):
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True,
                    read_message_history=True, attach_files=True, embed_links=True
                )

        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Ticket #{ticket_id} — {ticket_info['label']} — Ouvert par {user}"
            )
        except Exception as e:
            logger.error(f"Failed to create admin ticket channel: {e}")
            await interaction.followup.send("❌ Impossible de créer le salon ticket.", ephemeral=True)
            return

        await pool.execute(
            "UPDATE tickets SET channel_id = $1 WHERE id = $2",
            str(channel.id), ticket_id
        )

        welcome_embed = discord.Embed(
            title=f"{ticket_info['emoji']} {ticket_info['label']}",
            description=(
                f"**Ouvert par :** {user.mention}\n"
                f"**ID Ticket :** `{ticket_id}`\n\n"
                "Veuillez décrire votre demande en détail.\n"
                "Un membre du staff prendra en charge votre ticket dans les plus brefs délais."
            ),
            color=0x2b2d31,
            timestamp=datetime.datetime.utcnow()
        )
        try:
            welcome_embed.set_thumbnail(url=user.display_avatar.url)
        except Exception:
            pass

        view = discord.ui.View(timeout=None)
        view.add_item(ClaimAdminTicketButton(ticket_id))
        view.add_item(CloseAdminTicketButton(ticket_id))

        ping_parts = [user.mention]
        for role_id in get_admin_ticket_ping_roles(ticket_type_key):
            ping_parts.append(f"<@&{role_id}>")
        await channel.send(content=" ".join(ping_parts), embed=welcome_embed, view=view)

        await interaction.followup.send(
            f"✅ Votre ticket **{ticket_info['label']}** a été ouvert : {channel.mention}",
            ephemeral=True
        )
        await log_to_db('info', f'Admin ticket #{ticket_id} ({ticket_info["label"]}) opened by {user} in {guild.name}')
        await log_ticket_event(
            guild, "open", ticket_id, ticket_type_key,
            creator_id=str(user.id), channel=channel,
            opened_at=datetime.datetime.utcnow()
        )
    except Exception as e:
        logger.error(f"Error in handle_admin_ticket_creation: {traceback.format_exc()}")
        try:
            await log_to_db('error', f'Error in handle_admin_ticket_creation: {e}')
        except Exception:
            pass
        try:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Une erreur est survenue.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Une erreur est survenue.", ephemeral=True)
        except Exception:
            pass


async def handle_admin_claim(interaction: discord.Interaction, ticket_id: int):
    try:
        await interaction.response.defer(ephemeral=True)
        if not pool:
            await interaction.followup.send("❌ Base de données indisponible.", ephemeral=True)
            return

        ticket = await pool.fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
        if not ticket:
            await interaction.followup.send("❌ Ticket introuvable.", ephemeral=True)
            return

        if ticket['status'] == 'closed':
            await interaction.followup.send("❌ Ce ticket est fermé.", ephemeral=True)
            return

        if ticket['claimer_id']:
            await interaction.followup.send(
                f"❌ Ce ticket a déjà été pris en charge par <@{ticket['claimer_id']}>.",
                ephemeral=True
            )
            return

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ Serveur introuvable.", ephemeral=True)
            return

        member = interaction.user
        allowed_role_ids = set(get_admin_ticket_view_roles(ticket['ticket_type']))
        member_role_ids = {r.id for r in getattr(member, 'roles', [])}
        if not (allowed_role_ids & member_role_ids):
            await interaction.followup.send(
                "❌ Vous n'avez pas le rôle requis pour prendre ce ticket en charge.",
                ephemeral=True
            )
            return

        claimed_row = await pool.fetchrow(
            """
            UPDATE tickets
               SET status = 'open',
                   claimer_id = $1,
                   claimed_at = NOW()
             WHERE id = $2
               AND claimer_id IS NULL
               AND status != 'closed'
            RETURNING id
            """,
            str(member.id), ticket_id
        )
        if not claimed_row:
            current = await pool.fetchrow("SELECT status, claimer_id FROM tickets WHERE id = $1", ticket_id)
            if current and current['claimer_id']:
                await interaction.followup.send(
                    f"❌ Ce ticket vient d'être pris en charge par <@{current['claimer_id']}>.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send("❌ Ce ticket n'est plus disponible.", ephemeral=True)
            return

        channel = interaction.channel
        ticket_info = ADMIN_TICKET_TYPES.get(ticket['ticket_type'], {})
        creator_id = ticket['user_id']

        creator_short = make_short_name(member)
        new_name = f"{ticket_info.get('circle', '')}{ticket_info.get('short', 'ticket')}-{creator_short}-claimed"
        try:
            await channel.edit(name=new_name, reason=f"Admin ticket #{ticket_id} pris en charge par {member}")
        except Exception:
            pass

        ping_content = f"<@{creator_id}>"

        claim_embed = discord.Embed(
            description=f"✅ Ticket pris en charge par {member.mention}.",
            color=0x2ecc71,
            timestamp=datetime.datetime.utcnow()
        )

        try:
            close_only_view = discord.ui.View(timeout=None)
            close_only_view.add_item(CloseAdminTicketButton(ticket_id))
            await interaction.message.edit(view=close_only_view)
        except Exception:
            pass

        await channel.send(content=ping_content, embed=claim_embed)
        await interaction.followup.send("✅ Ticket pris en charge.", ephemeral=True)
        await log_to_db('info', f'Admin ticket #{ticket_id} claimed by {member} in {guild.name}')
        await log_ticket_event(
            guild, "claim", ticket_id, ticket['ticket_type'],
            creator_id=creator_id, channel=channel,
            claimer_id=str(member.id),
            claimed_at=datetime.datetime.utcnow()
        )
    except Exception as e:
        logger.error(f"Error in handle_admin_claim: {traceback.format_exc()}")
        try:
            await log_to_db('error', f'Error in handle_admin_claim: {e}')
        except Exception:
            pass
        try:
            await interaction.followup.send("❌ Une erreur est survenue.", ephemeral=True)
        except Exception:
            pass


async def handle_close_admin_ticket(interaction: discord.Interaction, ticket_id: int):
    try:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user

        if not guild or not pool:
            await interaction.followup.send("❌ Erreur de configuration.", ephemeral=True)
            return

        ticket = await pool.fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
        if not ticket:
            await interaction.followup.send("❌ Ticket introuvable.", ephemeral=True)
            return

        allowed_role_ids = set(get_admin_ticket_view_roles(ticket['ticket_type']))
        member_role_ids = {r.id for r in getattr(member, 'roles', [])}
        is_creator = str(member.id) == ticket['user_id']
        has_role = bool(allowed_role_ids & member_role_ids)

        if not is_creator and not has_role:
            await interaction.followup.send(
                "❌ Vous n'avez pas la permission de fermer ce ticket.",
                ephemeral=True
            )
            return

        if is_creator and not has_role:
            await interaction.followup.send(
                "❌ Vous ne pouvez pas fermer votre propre ticket. Demandez à un membre du staff.",
                ephemeral=True
            )
            return

        await pool.execute(
            "UPDATE tickets SET status = 'closed' WHERE id = $1",
            ticket_id
        )

        channel = interaction.channel
        try:
            close_embed = discord.Embed(
                title="🔒 Ticket fermé",
                description=f"Fermé par {member.mention}. Le salon sera supprimé dans 5 secondes.",
                color=0xed4245,
                timestamp=datetime.datetime.utcnow(),
            )
            await channel.send(embed=close_embed)
        except Exception:
            pass

        try:
            await interaction.followup.send("✅ Fermeture du ticket en cours...", ephemeral=True)
        except Exception:
            pass

        await log_to_db('info', f'Admin ticket #{ticket_id} closed by {member}')
        try:
            _claimer_id = ticket['claimer_id']
        except Exception:
            _claimer_id = None
        try:
            _claimed_at = ticket['claimed_at']
        except Exception:
            _claimed_at = None
        await log_ticket_event(
            guild, "close", ticket_id, ticket['ticket_type'],
            creator_id=ticket['user_id'], channel=channel,
            claimer_id=_claimer_id,
            closer=member,
            claimed_at=_claimed_at
        )

        await asyncio.sleep(5)
        try:
            await channel.delete(reason=f"Admin ticket #{ticket_id} fermé par {member}")
        except Exception as e:
            logger.error(f"Failed to delete admin ticket channel #{ticket_id}: {e}")
    except Exception as e:
        logger.error(f"Error in handle_close_admin_ticket: {traceback.format_exc()}")
        try:
            await log_to_db('error', f'Error in handle_close_admin_ticket: {e}')
        except Exception:
            pass
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Une erreur est survenue.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Une erreur est survenue.", ephemeral=True)
        except Exception:
            pass


@bot.tree.command(name="logsadmin", description="Créer le salon de logs des tickets Admin.")
@app_commands.default_permissions(administrator=True)
async def logs_command(interaction: discord.Interaction):
    try:
        if not await is_bot_owner_or_server_owner(interaction.guild, interaction.user.id):
            await interaction.response.send_message("Seul le propriétaire du bot ou le créateur du serveur peut utiliser cette commande.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, embed_links=True),
        }
        for role_id in (ROLE_GERANT_RP, ROLE_GERANT_STAFF, ROLE_ADMINISTRATEUR, ROLE_FULL_ACCESS_1, ROLE_FULL_ACCESS_2):
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=False)

        category = discord.utils.get(guild.categories, name=TICKET_LOG_CATEGORY)
        if not category:
            category = await guild.create_category(TICKET_LOG_CATEGORY, overwrites=overwrites)
        else:
            try:
                await category.edit(overwrites=overwrites)
            except Exception:
                pass

        existing = discord.utils.get(category.text_channels, name=TICKET_LOG_CHANNEL)
        if not existing:
            log_ch = await guild.create_text_channel(
                TICKET_LOG_CHANNEL,
                category=category,
                overwrites=overwrites,
                topic="Logs des tickets Admin RP — MssClick"
            )
        else:
            log_ch = existing
            try:
                await log_ch.edit(overwrites=overwrites)
            except Exception:
                pass

        embed = discord.Embed(
            title="✅ Logs Tickets Admin configurés",
            description=(
                f"Le salon {log_ch.mention} a été créé/configuré.\n\n"
                "Les événements suivants y seront enregistrés :\n"
                "> 🟢 Ouverture d'un ticket (type, créateur)\n"
                "> 🟡 Prise en charge (par qui, quand)\n"
                "> 🔴 Fermeture du ticket (par qui)"
            ),
            color=0x2b2d31
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        await log_to_db('info', f'/logsadmin used by {interaction.user} in {guild.name}')
    except Exception:
        logger.error(f"Error in /logsadmin command: {traceback.format_exc()}")
        try:
            await interaction.followup.send("Une erreur est survenue.", ephemeral=True)
        except Exception:
            pass


@bot.tree.command(name="ticketadmin", description="Envoyer le panneau de tickets Admin RP dans ce salon.")
@app_commands.default_permissions(administrator=True)
async def ticketadmin_command(interaction: discord.Interaction):
    try:
        view = TicketAdminLayout()
        await interaction.channel.send(view=view)

        await interaction.response.send_message("✅ Panneau de tickets Admin envoyé.", ephemeral=True)
        await log_to_db('info', f'/ticketadmin panel sent by {interaction.user} in #{interaction.channel}')
    except Exception as e:
        logger.error(f"Error in /ticketadmin command: {traceback.format_exc()}")
        try:
            await log_to_db('error', f'Error in /ticketadmin: {e}')
        except Exception:
            pass
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Une erreur est survenue.", ephemeral=True)
        except Exception:
            pass


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.error(f"App command error: {error}\n{traceback.format_exc()}")
    try:
        await log_to_db('error', f'App command error: {error}')
    except Exception:
        pass
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message("Une erreur est survenue.", ephemeral=True)
        else:
            await interaction.followup.send("Une erreur est survenue.", ephemeral=True)
    except Exception:
        pass


async def main():
    await init_db()
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN is not set.")
        return
    logger.info("Starting bot...")
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
