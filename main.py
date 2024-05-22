import datetime
import os
import shelve
from dotenv import load_dotenv
import random

import discord
from discord import app_commands
from discord.ext import tasks, commands

load_dotenv()  # load all the variables from the env file
token = os.getenv("TOKEN")

RDL = discord.Object(id=296802696243970049)
roles = [894572168426430474, 296803054403977216]


class Blender(discord.Client):
    def __init__(self, *, intent: discord.Intents):
        super().__init__(intents=intent)
        self.pharmacy = None
        self.morgue = None

        self.blend_time = datetime.time(5, 0, 0)
        self.blend = ""
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.copy_global_to(guild=RDL)
        await self.tree.sync(guild=RDL)


intents = discord.Intents.default()
client = Blender(intent=intents)


@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("------")
    client.morgue = await client.fetch_channel(362784581344034816)
    client.pharmacy = await client.fetch_channel(419900766279696384)
    await client.change_presence(
        activity=discord.CustomActivity(
            "Making coffee ☕", emoji=discord.PartialEmoji.from_str("coffee")
        )
    )
    get_blend.start()


@client.tree.command(
    name="blend",
    description="Blends a level today",
)
@commands.has_any_role(*roles)
@app_commands.describe(level="Level to blend")
async def blend_today(interaction: discord.Interaction, level: str):
    client.blend = level
    await interaction.response.send_message(f"Blending {level} today.")
    print(f"Blending {level} today.")


@client.tree.command(
    name="randomblend", description="Adds level to list of random blends"
)
@commands.has_any_role(*roles)
@app_commands.describe(level="Level to blend")
async def random_blend(interaction: discord.Interaction, level: str):
    with open("random.txt", "a") as f:
        f.write(f"{level}\n")
    await interaction.response.send_message(f"Blending {level} randomly.")
    print(f"Blending {level} randomly.")


@client.tree.command(
    name="queueblend",
    description="Schedules level to blend on date",
)
@commands.has_any_role(*roles)
@app_commands.describe(level="level to blend", date="MM DD")
async def date_blend(interaction: discord.Interaction, level: str, date: str):
    db = shelve.open("scheduled")
    db[date] = level
    db.close()
    await interaction.response.send_message(f"Blending {level} on {date}.")
    print(f"Blending {level} on {date}.")


@client.tree.command(
    name="forceblend",
    description="Blends right now",
)
@commands.has_any_role(*roles)
@app_commands.describe(level="Level to blend")
async def force_blend(interaction: discord.Interaction, level: str):
    await blend_level(level)
    await interaction.response.send_message("Blending!")
    print(f"Force blend {level}.")


@client.tree.command(name="viewqueue", description="View levels in queue")
@commands.has_any_role(*roles)
async def view_queue(interaction: discord.Interaction):
    db = shelve.open("scheduled")
    res = ""
    for k, v in sorted(dict(db).items()):
        res += f"{k}: {v}\n"
    await interaction.response.send_message(res)


@client.tree.command(name="viewrandom", description="View levels in random")
@commands.has_any_role(*roles)
async def view_random(interaction: discord.Interaction):
    with open("random.txt", "r") as f:
        await interaction.response.send_message(f.read())


@tasks.loop(time=client.blend_time)
async def get_blend():
    if client.blend:
        await blend_level(client.blend)
        client.blend = ""
    else:
        try:
            today = datetime.datetime.now(datetime.UTC).today()
            today_str = today.strftime("%m %d")
            db = shelve.open("scheduled")
            await blend_level(db[today_str])
            del db[today_str]
        except KeyError:
            levels = open("random.txt").read().splitlines()
            print(levels)
            await blend_level(levels.pop(random.randrange(len(levels))))
            with open("random.txt", "w") as f:
                for level in levels:
                    f.write(f"{level}\n")


async def blend_level(level: str):
    await client.morgue.send(f"rdzip^blend {level}")
    print(f"Blending {level} at {datetime.datetime.now()}")


client.run(token)
