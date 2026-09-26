import asyncio
import json
import os
from datetime import datetime, timezone
import aiohttp
import discord                                         from discord import app_commands
from discord.ext import commands

from config import debug, rover_token
                                                       ROVER_API_BASE = "https://registry.rover.link/api"
ROBLOX_GROUPS_API = "https://groups.roblox.com/v1/groups"


class RoleSetupView(discord.ui.View):

  def __init__(self, roles_data: list):
    super().__init__(timeout=300)
    self.all_valid_roles = [r for r in roles_data if r["weight"] > 1]                                         
    self.operational_role_ids = set()
    self.permitted_role_ids = set()

    self.current_step = 1
    self.current_page = 0                                  self.per_page = 23
    self.is_saved = False
    self.update_components()                           
  def get_current_page_roles(self):                        # На обоих шагах показываем все роли с весом > 1
    roles_source = self.all_valid_roles                
    start_idx = self.current_page * self.per_page
    end_idx = start_idx + self.per_page                    return roles_source, start_idx, end_idx

  def update_components(self):
    self.clear_items()

    roles_source, start_idx, end_idx = self.get_current_page_roles()
    total_pages = (len(roles_source) + self.per_page - 1) // self.per_page
    if total_pages == 0:
      total_pages = 1                                  
    if self.current_page >= total_pages:
      self.current_page = max(0, total_pages - 1)
      roles_source, start_idx, end_idx = self.get_current_page_roles()                                        
    page_roles = roles_source[start_idx:end_idx]       
    options = []
    for r in page_roles:
      if self.current_step == 1:
        is_default = r["id"] in self.operational_role_ids
      else:
        is_default = r["id"] in self.permitted_role_ids
      options.append(
          discord.SelectOption(
              label=str(r["name"])[:100],
              value=str(r["id"]),                                    description=f"Weight: {r['weight']}",
              default=is_default,
          )
      )

    if options:                                              step_desc = "operational roles" if self.current_step == 1 else "manage lower ranks roles"
      self.select_menu = discord.ui.Select(                      placeholder=(
              f"Select {step_desc} "
              f"(Page {self.current_page + 1}/{total_pages})..."
          ),
          min_values=0,                                          max_values=len(options),
          options=options,
      )                                                      self.select_menu.callback = self.select_callback       self.add_item(self.select_menu)

    if total_pages > 1:
      prev_button = discord.ui.Button(
          label="⬅️ Previous",
          style=discord.ButtonStyle.secondary,
          disabled=(self.current_page == 0),
          row=1,
      )
      prev_button.callback = self.prev_page_callback         self.add_item(prev_button)

      next_button = discord.ui.Button(
          label="Next ➡️",
          style=discord.ButtonStyle.secondary,                   disabled=(self.current_page >= total_pages - 1),
          row=1,
      )
      next_button.callback = self.next_page_callback         self.add_item(next_button)                       
    if self.current_step == 1:
      confirm_op_button = discord.ui.Button(
          label="Confirm Operational Roles", style=discord.ButtonStyle.green, row=2
      )
      confirm_op_button.callback = self.next_stage_callback
      self.add_item(confirm_op_button)
    else:                                                    back_button = discord.ui.Button(
          label="⬅️ Back", style=discord.ButtonStyle.secondary, row=2
      )
      back_button.callback = self.back_stage_callback
      self.add_item(back_button)

      save_button = discord.ui.Button(
          label="Save Final Configuration", style=discord.ButtonStyle.green, row=2
      )                                                      save_button.callback = self.save_callback
      self.add_item(save_button)

  def capture_current_selection(self):
    if hasattr(self, "select_menu"):
      roles_source, start_idx, end_idx = self.get_current_page_roles()
      page_role_ids = {r["id"] for r in roles_source[start_idx:end_idx]}
      selected_on_page = {int(val) for val in self.select_menu.values}

      if self.current_step == 1:
        self.operational_role_ids -= page_role_ids
        self.operational_role_ids |= selected_on_page
      else:
        self.permitted_role_ids -= page_role_ids
        self.permitted_role_ids |= selected_on_page

  async def select_callback(self, interaction: discord.Interaction):                                              self.capture_current_selection()
    await interaction.response.defer()

  async def prev_page_callback(self, interaction: discord.Interaction):
    self.capture_current_selection()
    if self.current_page > 0:
      self.current_page -= 1
      self.update_components()
      await interaction.response.edit_message(view=self)                                                          else:
      await interaction.response.defer()               
  async def next_page_callback(self, interaction: discord.Interaction):
    self.capture_current_selection()                       roles_source, _, _ = self.get_current_page_roles()     total_pages = (len(roles_source) + self.per_page - 1) // self.per_page
    if self.current_page < total_pages - 1:
      self.current_page += 1
      self.update_components()
      await interaction.response.edit_message(view=self)                                                          else:
      await interaction.response.defer()

  async def next_stage_callback(self, interaction: discord.Interaction):
    self.capture_current_selection()
    self.current_step = 2
    self.current_page = 0
    self.update_components()
                                                           embed_text = (
        "**Step 2/2: Manage Lower Ranks**\n"
        "Select roles that have permission to use management commands (`/rank promote`, `/rank demote`, `/rank set`):"
    )
    await interaction.response.edit_message(content=embed_text, view=self)

  async def back_stage_callback(self, interaction: discord.Interaction):
    self.capture_current_selection()
    self.current_step = 1
    self.current_page = 0                                  self.update_components()

    embed_text = (
        "**Step 1/2: Operational Roles**\n"
        "Select roles that can be targeted by bot actions (`/rank promote`, `/rank demote`, `/rank set`):"
    )
    await interaction.response.edit_message(content=embed_text, view=self)
                                                         async def save_callback(self, interaction: discord.Interaction):
    self.capture_current_selection()
    self.is_saved = True
    await interaction.response.send_message(
        "✅ Configuration successfully saved to JSON!", ephemeral=True
    )
    self.stop()


class VerifyGroupCog(commands.Cog):

  def __init__(self, bot: commands.Bot):
    self.bot = bot

  async def _fetch_rover_data(self, guild_id: int, user_id: int) -> dict:
    url = f"{ROVER_API_BASE}/guilds/{guild_id}/discord-to-roblox/{user_id}"
    headers = {
        "Authorization": f"Bearer {rover_token}",
        "Accept": "application/json",
    }
    async with aiohttp.ClientSession() as session:
      async with session.get(url, headers=headers) as response:
        if response.status == 200:
          return await response.json()
        elif response.status == 404:
          return None
        else:
          text = await response.text()
          raise Exception(f"RoVer API Error [{response.status}]: {text}")
                                                         async def _send_access_request(self, guild_id: int, user_id: int):
    url = f"{ROVER_API_BASE}/guilds/{guild_id}/access-requests/{user_id}"
    headers = {
        "Authorization": f"Bearer {rover_token}",
        "Content-Type": "application/json",
    }                                                      async with aiohttp.ClientSession() as session:
      async with session.put(url, headers=headers, json={}) as response:
        if response.status not in (200, 201):
          text = await response.text()
          print(f"⚠️ Не удалось отправить запрос доступа через RoVer: {text}")

  async def _fetch_group_roles(self, group_id: int) -> list:
    url = f"{ROBLOX_GROUPS_API}/{group_id}/roles"
    async with aiohttp.ClientSession() as session:
      async with session.get(url) as response:
        if response.status != 200:
          raise Exception(f"Failed to fetch group roles (Status {response.status})")
        data = await response.json()                           raw_roles = data.get("roles", [])

        raw_roles.sort(key=lambda x: x.get("rank", 0))

        formatted_roles = []
        for index, role in enumerate(raw_roles):
          formatted_roles.append({
              "name": role.get("name"),                              "id": role.get("id"),
              "weight": index,
          })

        formatted_roles.sort(key=lambda x: x["weight"], reverse=True)
        return formatted_roles

  @app_commands.command(
      name="verify",                                         description="Verify server ownership, fetch group roles and setup configuration",
  )
  @app_commands.describe(group_id="The Roblox Group ID to setup")
  async def verify(self, interaction: discord.Interaction, group_id: int):
    if interaction.user.id != interaction.guild.owner_id and interaction.user.id != debug:
      await interaction.response.send_message(
          "❌ Only the **guild owner** can use this command.", ephemeral=True
      )                                                      return

    await interaction.response.defer(ephemeral=True)

    guild_id = interaction.guild.id
    user_id = interaction.user.id                      
    try:
      data = await self._fetch_rover_data(guild_id, user_id)
                                                             if not data or not data.get("robloxId"):
        await interaction.followup.send(
            "🔒 Your Roblox account data is private or unlinked in RoVer. "
            "An access request has been sent to your DMs. Please accept it, "
            "waiting up to 1 minute...",
            ephemeral=True,
        )                                                      await self._send_access_request(guild_id, user_id)
        await asyncio.sleep(60)
        data = await self._fetch_rover_data(guild_id, user_id)                                                
      if not data or not data.get("robloxId"):
        await interaction.followup.send(
            "❌ Verification failed. Account not linked or request ignored.",                                             ephemeral=True,
        )
        return

      roblox_username = data.get("cachedUsername", "Unknown")
                                                             roles_list = await self._fetch_group_roles(group_id)

      view = RoleSetupView(roles_list)
      await interaction.followup.send(                           f"✅ **Verified as** `{roblox_username}`.\n\n"                                                                "**Step 1/2: Operational Roles**\n"
          "Select roles that can be targeted by bot actions (`/rank promote`, `/rank demote`, `/rank set`):",
          view=view,
          ephemeral=True,
      )

      await view.wait()

      if not view.is_saved:
        await interaction.followup.send(
            "⏱️ Setup timed out or was cancelled.", ephemeral=True
        )
        return

      complete_roles = {}
      operational_roles = []
      permitted_manage_lower_roles = []
      immutable_roles = []

      operational_ids_set = set(view.operational_role_ids)                                                          permitted_ids_set = set(view.permitted_role_ids)

      for r in roles_list:
        r_name = r["name"]
        r_id = r["id"]
        r_weight = r["weight"]

        complete_roles[r_name] = {"role_id": r_id, "weight": r_weight}

        if r_id in operational_ids_set:
          operational_roles.append(r_name)
                                                               if r_id in permitted_ids_set:
          permitted_manage_lower_roles.append(r_name)

        if r_weight <= 1 or r_id not in operational_ids_set:
          immutable_roles.append(r_name)

      os.makedirs("guild_ranks", exist_ok=True)              file_path = os.path.join("guild_ranks", f"{guild_id}.json")

      guild_config = {
          "guild_id": guild_id,
          "group_id": group_id,
          "complete_roles": complete_roles,
          "operational_roles": operational_roles,
          "permitted_manage_lower_roles": permitted_manage_lower_roles,
          "immutable_roles": immutable_roles,
      }

      with open(file_path, "w", encoding="utf-8") as f:
        json.dump(guild_config, f, ensure_ascii=False, indent=4)
                                                             await interaction.followup.send(
          f"🎉 **Setup complete!** Saved configuration for group `{group_id}` into `guild_ranks/{guild_id}.json`.",
          ephemeral=True,
      )

    except Exception as e:                                   await interaction.followup.send(
          f"🚨 An unexpected error occurred: `{e}`", ephemeral=True
      )


async def setup(bot: commands.Bot):
  if bot.get_cog("VerifyGroupCog"):
    await bot.remove_cog("VerifyGroupCog")
  await bot.add_cog(VerifyGroupCog(bot))
