from __future__ import annotations                     
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
import os
import json

from config import rover_token, debug                  
ROVER_API_BASE = "https://registry.rover.link/api"
ROBLOX_GROUPS_API = "https://groups.roblox.com/v1/groups"
                                                       
class RanksManage(commands.Cog):
    """Объединенный ког для управления рангами в Roblox группе через субкоманды /rank."""
                                                           COLOR_RED = discord.Color.red()
    COLOR_GREEN = discord.Color.green()
    COLOR_BLUE = discord.Color.blue()

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Создаем группу команд /rank с субкомандами promote, demote, set
    rank_group = app_commands.Group(name="rank", description="Manage Roblox group ranks")                     
    # --- Вспомогательные методы ---                   
    def _load_guild_config(self, guild_id: int) -> dict | None:
        """Загружает конфигурацию гильдии из файла guild_ranks/{guild_id}.json."""
        file_path = os.path.join("guild_ranks", f"{guild_id}.json")                                                   if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None                                
    async def _fetch_rover_roblox_id(self, guild_id: int, user_id: int) -> int | None:                                """Получает Roblox ID пользователя в конкретном сервере через RoVer API."""                                   url = f"{ROVER_API_BASE}/guilds/{guild_id}/discord-to-roblox/{user_id}"
        headers = {"Authorization": f"Bearer {rover_token}", "Accept": "application/json"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("robloxId")                return None

    async def _get_roblox_user_id(self, username_or_id: str) -> int | None:
        """Конвертирует никнейм Roblox в ID или проверяет переданный ID."""
        if username_or_id.isdigit():
            return int(username_or_id)
                                                               url = "https://users.roblox.com/v1/usernames/users"
        payload = {"usernames": [username_or_id], "excludeBannedUsers": True}
                                                               async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("data"):
                        return data["data"][0]["id"]
        return None

    async def _get_user_roblox_role(self, group_id: int, user_id: int) -> dict | None:                                """Получает текущую роль юзера в Roblox группе."""
        url = f"https://groups.roblox.com/v1/users/{user_id}/groups/roles"

        async with aiohttp.ClientSession() as session:             async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()                           for group in data.get("data", []):
                        if group.get("group", {}).get("id") == group_id:
                            return group.get("role")           return None

    async def _set_roblox_role(self, group_id: int, user_id: int, new_role_id: int) -> bool:
        """Устанавливает новую роль через Roblox Cloud API (Используется токен группы из конфига или общий cloud_api)."""
        # Примечание: если у вас cloud_api хранится в общих настройках или в конфиге гильдии — подставьте нужный источник
        from config import cloud_api
        url = f"https://apis.roblox.com/cloud/v2/groups/{group_id}/memberships/{user_id}"
        headers = {                                                "x-api-key": cloud_api,
            "Content-Type": "application/json",
        }
        payload = {"role": f"groups/{group_id}/roles/{new_role_id}"}                                          
        async with aiohttp.ClientSession() as session:             async with session.patch(url, headers=headers, json=payload) as response:
                return response.status == 200          
    async def _validate_permissions(self, interaction: discord.Interaction, config: dict) -> tuple[int, int]:
        """
        Проверяет, привязан ли пользователь через RoVer, состоит ли он в группе,
        и имеет ли право управлять рангами (находится ли в permitted_manage_lower_roles).
        Возвращает (roblox_id, role_weight) выполняющего команду.                                                     """
        guild_id = interaction.guild.id
        group_id = config["group_id"]                  
        # 1. Получаем Roblox ID через RoVer
        executor_roblox_id = await self._fetch_rover_roblox_id(guild_id, interaction.user.id)
        if not executor_roblox_id and interaction.user.id != debug:
            raise ValueError("Your Discord account is not linked with RoVer for this server.")

        # Если владелец или дебаг-юзер без привязки (на всякий случай)                                                if not executor_roblox_id and interaction.user.id == debug:
            return 0, 999999                           
        # 2. Получаем роль выполняющего в группе
        executor_role_data = await self._get_user_roblox_role(group_id, executor_roblox_id)
        if not executor_role_data:
            raise ValueError("You are not a member of the linked Roblox group.")

        executor_role_name = executor_role_data["name"]        permitted_roles = config.get("permitted_manage_lower_roles", [])

        # 3. Проверяем, есть ли роль в разрешенных для управления
        if executor_role_name not in permitted_roles and interaction.user.id != interaction.guild.owner_id:
            raise ValueError("You do not have permission to use rank management commands.")

        complete_roles = config.get("complete_roles", {})
        executor_weight = complete_roles.get(executor_role_name, {}).get("weight", -1)

        return executor_roblox_id, executor_weight     
    # --- Подкоманда: /rank promote ---
    @rank_group.command(name="promote", description="Promote a group member by 1 rank")
    @app_commands.describe(user="Roblox username or user ID")                                                     async def promote(self, interaction: discord.Interaction, user: str):
        await interaction.response.defer(thinking=True)
        config = self._load_guild_config(interaction.guild.id)
        if not config:
            await interaction.followup.send("❌ Server configuration not found. Run `/verify` first.", ephemeral=True)
            return                                     
        try:
            _, executor_weight = await self._validate_permissions(interaction, config)
            group_id = config["group_id"]
            complete_roles = config["complete_roles"]
            operational_roles = config["operational_roles"]
                                                                   # Получаем ID целевого юзера
            target_roblox_id = await self._get_roblox_user_id(user)
            if not target_roblox_id:
                raise ValueError(f"Roblox user '{user}' not found.")

            target_role_data = await self._get_user_roblox_role(group_id, target_roblox_id)
            if not target_role_data:                                   raise ValueError("Target user is not in the group.")

            curr_name = target_role_data["name"]
            curr_id = target_role_data["id"]
            curr_weight = complete_roles.get(curr_name, {}).get("weight", -1)

            # Проверки иерархии и операционных ролей
            if curr_weight >= executor_weight and interaction.user.id != interaction.guild.owner_id:
                raise ValueError("You cannot modify users with a rank equal to or higher than yours.")        
            if curr_name not in operational_roles:
                raise ValueError(f"The role '{curr_name}' is not within operational roles.")

            next_weight = curr_weight + 1
            next_name, next_id = None, None
            for r_name, r_info in complete_roles.items():
                if r_info["weight"] == next_weight:
                    next_name = r_name                                     next_id = r_info["role_id"]
                    break                              
            if not next_name or next_name not in operational_roles:
                raise ValueError("Maximum possible rank reached or next rank is outside operational roles.")  
            success = await self._set_roblox_role(group_id, target_roblox_id, next_id)
            if not success:
                raise RuntimeError("Failed to execute request to Roblox Cloud API.")
                                                                   await interaction.followup.send(f"✅ Successfully promoted **{user}** from **{curr_name}** to **{next_name}**.")

        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred: {e}", ephemeral=True)

    # --- Подкоманда: /rank demote ---                     @rank_group.command(name="demote", description="Demote a group member by 1 rank")                             @app_commands.describe(user="Roblox username or user ID")
    async def demote(self, interaction: discord.Interaction, user: str):                                              await interaction.response.defer(thinking=True)
        config = self._load_guild_config(interaction.guild.id)
        if not config:
            await interaction.followup.send("❌ Server configuration not found. Run `/verify` first.", ephemeral=True)
            return

        try:
            _, executor_weight = await self._validate_permissions(interaction, config)
            group_id = config["group_id"]
            complete_roles = config["complete_roles"]              operational_roles = config["operational_roles"]

            target_roblox_id = await self._get_roblox_user_id(user)
            if not target_roblox_id:
                raise ValueError(f"Roblox user '{user}' not found.")                                          
            target_role_data = await self._get_user_roblox_role(group_id, target_roblox_id)
            if not target_role_data:
                raise ValueError("Target user is not in the group.")

            curr_name = target_role_data["name"]
            curr_id = target_role_data["id"]
            curr_weight = complete_roles.get(curr_name, {}).get("weight", -1)

            if curr_weight >= executor_weight and interaction.user.id != interaction.guild.owner_id:
                raise ValueError("You cannot modify users with a rank equal to or higher than yours.")        
            if curr_name not in operational_roles:
                raise ValueError(f"The role '{curr_name}' is not within operational roles.")

            next_weight = curr_weight - 1
            next_name, next_id = None, None
            for r_name, r_info in complete_roles.items():
                if r_info["weight"] == next_weight:                        next_name = r_name
                    next_id = r_info["role_id"]                            break

            if not next_name or next_name not in operational_roles:
                raise ValueError("Minimum possible rank reached or target rank is outside operational roles.")
                                                                   success = await self._set_roblox_role(group_id, target_roblox_id, next_id)
            if not success:
                raise RuntimeError("Failed to execute request to Roblox Cloud API.")

            await interaction.followup.send(f"✅ Successfully demoted **{user}** from **{curr_name}** to **{next_name}**.")

        except Exception as e:                                     await interaction.followup.send(f"❌ An error occurred: {e}", ephemeral=True)

    # --- Подкоманда: /rank set ---
    @rank_group.command(name="set", description="Set a user to a specific operational rank")
    @app_commands.describe(user="Roblox username or user ID", rank="Target rank name")
    async def set_rank(self, interaction: discord.Interaction, user: str, rank: str):
        await interaction.response.defer(thinking=True)
        config = self._load_guild_config(interaction.guild.id)                                                        if not config:
            await interaction.followup.send("❌ Server configuration not found. Run `/verify` first.", ephemeral=True)
            return                                     
        try:
            _, executor_weight = await self._validate_permissions(interaction, config)
            group_id = config["group_id"]
            complete_roles = config["complete_roles"]
            operational_roles = config["operational_roles"]

            if rank not in complete_roles or rank not in operational_roles:
                raise ValueError(f"The rank '{rank}' is invalid or outside operational roles.")

            target_role_info = complete_roles[rank]
            target_weight = target_role_info["weight"]
            target_id = target_role_info["role_id"]

            # Проверяем, что целевой ранг ниже ранга того, кто выполняет команду
            if target_weight >= executor_weight and interaction.user.id != interaction.guild.owner_id:
                raise ValueError("You cannot set a rank equal to or higher than your own.")                   
            target_roblox_id = await self._get_roblox_user_id(user)
            if not target_roblox_id:
                raise ValueError(f"Roblox user '{user}' not found.")

            target_role_data = await self._get_user_roblox_role(group_id, target_roblox_id)                               if not target_role_data:
                raise ValueError("Target user is not in the group.")                                          
            curr_name = target_role_data["name"]
            curr_weight = complete_roles.get(curr_name, {}).get("weight", -1)
                                                                   if curr_weight >= executor_weight and interaction.user.id != interaction.guild.owner_id:
                raise ValueError("You cannot modify users with a rank equal to or higher than yours.")

            success = await self._set_roblox_role(group_id, target_roblox_id, target_id)                                  if not success:
                raise RuntimeError("Failed to execute request to Roblox Cloud API.")

            await interaction.followup.send(f"✅ Successfully set rank for **{user}** to **{rank}**.")

        except Exception as e:                                     await interaction.followup.send(f"❌ An error occurred: {e}", ephemeral=True)                     
    @set_rank.autocomplete("rank")                         async def rank_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        config = self._load_guild_config(interaction.guild.id)
        if not config:
            return []

        operational_roles = config.get("operational_roles", [])
        filtered = [name for name in operational_roles if current.lower() in name.lower()]                            return [app_commands.Choice(name=name, value=name) for name in filtered[:25]]
                                                       
async def setup(bot: commands.Bot):
    if bot.get_cog("RanksManage"):
        bot.remove_cog("RanksManage")
    await bot.add_cog(RanksManage(bot))
