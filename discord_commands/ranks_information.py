cat << 'EOF' > discord_commands/ranks_information.py
import json
import os
from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands


class RanksInformationCog(commands.Cog):

  def __init__(self, bot: commands.Bot):
    self.bot = bot

  ranks_group = app_commands.Group(
      name="ranks", description="Management commands for guild ranks"
  )

  @ranks_group.command(
      name="information",
      description="View the saved rank configuration for this guild",
  )
  async def ranks_information(self, interaction: discord.Interaction):
    if interaction.user.id != interaction.guild.owner_id:
      await interaction.response.send_message(
          "❌ Only the **guild owner** can use this command.", ephemeral=True
      )
      return

    guild_id = interaction.guild.id
    file_path = os.path.join("guild_ranks", f"{guild_id}.json")

    if not os.path.exists(file_path):
      await interaction.response.send_message(
          "❌ No configuration file found for this guild. Please run `/verify` first.",
          ephemeral=True,
      )
      return

    try:
      with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

      embeds = []

      guild = interaction.guild
      owner = guild.owner

      # Получаем канал для логов из конфига
      prog_channel_id = data.get("progression_channel_id")
      prog_channel = guild.get_channel(prog_channel_id) if prog_channel_id else None

      # 1. Basic Information (Первым)
      basic_embed = discord.Embed(
          title="📌 Basic Information",
          color=discord.Color.blue(),
          timestamp=datetime.now(timezone.utc),
      )
      basic_embed.add_field(
          name="Discord Guild",
          value=f"Name: `{guild.name}`\nID: `{guild_id}`",
          inline=True,
      )
      basic_embed.add_field(
          name="Guild Owner",
          value=f"Mention: {owner.mention if owner else 'Unknown'}\nID: `{guild.owner_id}`",
          inline=True,
      )
      basic_embed.add_field(
          name="Roblox Group ID",
          value=f"`{data.get('group_id')}`",
          inline=False,
      )
      basic_embed.add_field(
          name="Progression Logs Channel",
          value=f"{prog_channel.mention if prog_channel else 'Not set'} (`{prog_channel_id}`)",
          inline=False,
      )
      embeds.append(basic_embed)

      # 2. Complete Roles (Вторым)
      complete_roles = data.get("complete_roles", {})
      if complete_roles:
        sorted_roles = sorted(
            complete_roles.items(),
            key=lambda x: x[1].get("weight", 0),
            reverse=True,
        )

        comp_embed = discord.Embed(
            title="📋 Complete Roles Hierarchy",
            color=discord.Color.purple(),
        )

        current_chunk = ""
        for r_name, r_info in sorted_roles:
          line = f"**{r_name}**\n└ ID: `{r_info.get('role_id')}` | Weight: `{r_info.get('weight')}`\n\n"

          if len(current_chunk) + len(line) > 1000:
            comp_embed.add_field(name="\u200b", value=current_chunk, inline=False)
            current_chunk = ""

            if len(comp_embed.fields) >= 25:
              embeds.append(comp_embed)
              comp_embed = discord.Embed(
                  title="📋 Complete Roles Hierarchy (Continued)",
                  color=discord.Color.purple(),
              )

          current_chunk += line

        if current_chunk:
          comp_embed.add_field(name="\u200b", value=current_chunk, inline=False)

        embeds.append(comp_embed)

      # 3. Operational Roles (Третьим)
      op_roles = data.get("operational_roles", [])
      op_text = "\n".join([f"• {role}" for role in op_roles]) if op_roles else "*None*"

      op_embed = discord.Embed(
          title="⚡ Operational Roles",
          description=op_text[:4000] if len(op_text) <= 4000 else op_text[:3997] + "...",
          color=discord.Color.green(),
      )
      embeds.append(op_embed)

      # 4. Immune Roles (Четвертым)
      im_roles = data.get("immutable_roles", [])
      im_text = "\n".join([f"• {role}" for role in im_roles]) if im_roles else "*None*"

      im_embed = discord.Embed(
          title="🛡️ Immune Roles",
          description=im_text[:4000] if len(im_text) <= 4000 else im_text[:3997] + "...",
          color=discord.Color.gold(),
      )
      embeds.append(im_embed)

      if len(embeds) > 10:
        embeds = embeds[:10]

      await interaction.response.send_message(embeds=embeds, ephemeral=True)

    except Exception as e:
      await interaction.response.send_message(
          f"🚨 Error reading configuration file: `{e}`", ephemeral=True
      )


async def setup(bot: commands.Bot):
  await bot.add_cog(RanksInformationCog(bot))
EOF
