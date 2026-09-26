import asyncio
import json
import os
from datetime import datetime, timezone
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from config import rover_token

ROVER_API_BASE = "https://registry.rover.link/api"
ROBLOX_GROUPS_API = "https://groups.roblox.com/v1/groups"

BOT_OWNER_ID = 855164688802906142


class RoleSetupView(discord.ui.View):

  def __init__(self, roles_data: list):
    super().__init__(timeout=300)
    self.roles_data = [r for r in roles_data if r["weight"] > 1]
    self.selected_role_ids = set()
    self.current_page = 0
    self.per_page = 23
    self.is_saved = False
    self.update_components()

  def update_components(self):
    self.clear_items()

    total_pages = (
        len(self.roles_data) + self.per_page - 1
    ) // self.per_page
    if total_pages == 0:
      total_pages = 1

    start_idx = self.current_page * self.per_page
    end_idx = start_idx + self.per_page
    page_roles = self.roles_data[start_idx:end_idx]

    options = []
    for r in page_roles:
      is_default = r["id"] in self.selected_role_ids
      options.append(
          discord.SelectOption(
              label=str(r["name"])[:100],
              value=str(r["id"]),
              description=f"Weight: {r['weight']}",
              default=is_default,
          )
      )

    if options:
      self.select_menu = discord.ui.Select(
          placeholder=(
              f"Select operational roles (Page {self.current_page + 1}/"
              f"{total_pages})..."
          ),
          min_values=0,
          max_values=len(options),
          options=options,
      )
      self.select_menu.callback = self.select_callback
      self.add_item(self.select_menu)

    if total_pages > 1:
      prev_button = discord.ui.Button(
          label="⬅️ Previous",
          style=discord.ButtonStyle.secondary,
          disabled=(self.current_page == 0),
          row=1,
      )
      prev_button.callback = self.prev_page_callback
      self.add_item(prev_button)

      next_button = discord.ui.Button(
          label="Next ➡️",
          style=discord.ButtonStyle.secondary,
          disabled=(self.current_page >= total_pages - 1),
          row=1,
      )
      next_button.callback = self.next_page_callback
      self.add_item(next_button)

    save_button = discord.ui.Button(
        label="Save Configuration", style=discord.ButtonStyle.green, row=2
    )
    save_button.callback = self.save_callback
    self.add_item(save_button)

  def capture_current_selection(self):
    if hasattr(self, "select_menu"):
      start_idx = self.current_page * self.per_page
      end_idx = start_idx + self.per_page
      page_role_ids = {r["id"] for r in self.roles_data[start_idx:end_idx]}

      self.selected_role_ids -= page_role_ids
      selected_on_page = {int(val) for val in self.select_menu.values}
      self.selected_role_ids |= selected_on_page

  async def select_callback(self, interaction: discord.Interaction):
    self.capture_current_selection()
    await interaction.response.defer()

  async def prev_page_callback(self, interaction: discord.Interaction):
    self.capture_current_selection()
    if self.current_page > 0:
      self.current_page -= 1
      self.update_components()
      await interaction.response.edit_message(view=self)
    else:
      await interaction.response.defer()

  async def next_page_callback(self, interaction: discord.Interaction):
    self.capture_current_selection()
    total_pages = (
        len(self.roles_data) + self.per_page - 1
    ) // self.per_page
    if self.current_page < total_pages - 1:
      self.current_page += 1
      self.update_components()
      await interaction.response.edit_message(view=self)
    else:
      await interaction.response.defer()

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
    }
    async with aiohttp.ClientSession() as session:
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
        data = await response.json()
        raw_roles = data.get("roles", [])

        raw_roles.sort(key=lambda x: x.get("rank", 0))

        formatted_roles = []
        for index, role in enumerate(raw_roles):
          formatted_roles.append({
              "name": role.get("name"),
              "id": role.get("id"),
              "weight": index,
          })
        
        formatted_roles.sort(key=lambda x: x["weight"], reverse=True)
        return formatted_roles

  @app_commands.command(
      name="verify",
      description="Verify server ownership, fetch group roles and setup configuration",
  )
  @app_commands.describe(group_id="The Roblox Group ID to setup")
  async def verify(self, interaction: discord.Interaction, group_id: int):
    if interaction.user.id != interaction.guild.owner_id and interaction.user.id != BOT_OWNER_ID:
      await interaction.response.send_message(
          "❌ Only the **guild owner** can use this command.", ephemeral=True
      )
      return

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
        )
        await self._send_access_request(guild_id, user_id)
        await asyncio.sleep(60)
        data = await self._fetch_rover_data(guild_id, user_id)

      if not data or not data.get("robloxId"):
        await interaction.followup.send(
            "❌ Verification failed. Account not linked or request ignored.",
            ephemeral=True,
        )
        return

      roblox_username = data.get("cachedUsername", "Unknown")

      roles_list = await self._fetch_group_roles(group_id)

      view = RoleSetupView(roles_list)
      await interaction.followup.send(
          f"✅ **Test Mode (Ownership bypassed)** for (`{roblox_username}`).\n"
          "Please select your **operational roles** using the menu and pages below (highest weight at the top), then click **Save Configuration**:",
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
      immutable_roles = []

      selected_ids_set = set(view.selected_role_ids)

      for r in roles_list:
        r_name = r["name"]
        r_id = r["id"]
        r_weight = r["weight"]

        complete_roles[r_name] = {"role_id": r_id, "weight": r_weight}

        if r_weight <= 1:
          immutable_roles.append(r_name)
        elif r_id in selected_ids_set:
          operational_roles.append(r_name)
        else:
          immutable_roles.append(r_name)

      os.makedirs("guild_ranks", exist_ok=True)
      file_path = os.path.join("guild_ranks", f"{guild_id}.json")

      guild_config = {
          "guild_id": guild_id,
          "group_id": group_id,
          "complete_roles": complete_roles,
          "operational_roles": operational_roles,
          "immutable_roles": immutable_roles,
      }

      with open(file_path, "w", encoding="utf-8") as f:
        json.dump(guild_config, f, ensure_ascii=False, indent=4)

      await interaction.followup.send(
          f"🎉 **Setup complete!** Saved configuration for group `{group_id}` into `guild_ranks/{guild_id}.json`.",
          ephemeral=True,
      )

    except Exception as e:
      await interaction.followup.send(
          f"🚨 An unexpected error occurred: `{e}`", ephemeral=True
      )


async def setup(bot: commands.Bot):
  await bot.add_cog(VerifyGroupCog(bot))
    
