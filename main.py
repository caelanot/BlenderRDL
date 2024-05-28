import datetime
import json
import os
import random
import shelve
import urllib.parse
from dataclasses import dataclass
from typing import Any

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

RDL = discord.Object(id=296802696243970049)
ROLES = [894572168426430474, 296803054403977216]

BLEND_TIME = datetime.time(5, 0, 0)


@dataclass
class Config:
    token: str
    blend_webhook_url: str


def read_config() -> Config:
    # load all the variables from the .env file into environment variables
    load_dotenv()

    token = os.getenv("TOKEN")
    if token is None:
        print("Missing variable in .env: TOKEN")
        exit(1)

    blend_webhook_url = os.getenv("BLEND_WEBHOOK_URL")
    if blend_webhook_url is None:
        print("Missing variable in .env: BLEND_WEBHOOK_URL")
        exit(1)

    return Config(token, blend_webhook_url)


CONFIG = read_config()


class Blender(discord.Client):
    def __init__(self, *, intent: discord.Intents):
        super().__init__(intents=intent)
        self.pharmacy: discord.TextChannel
        self.morgue: discord.TextChannel

        self.to_blend: str | None = None
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.copy_global_to(guild=RDL)
        await self.tree.sync(guild=RDL)

    def get_text_channel(self, id: int) -> discord.TextChannel:
        channel = self.get_channel(id)
        if channel is None:
            raise Exception(f"Couldn't find channel with id {id}.")
        if not isinstance(channel, discord.TextChannel):
            raise Exception(f"Channel with id {id} is not a TextChannel.")
        return channel


client = Blender(intent=discord.Intents.default())


@client.event
async def on_ready():
    assert client.user is not None
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("------")
    client.morgue = client.get_text_channel(362784581344034816)
    client.pharmacy = client.get_text_channel(419900766279696384)
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
@commands.has_any_role(*ROLES)
@app_commands.describe(level="Level to blend")
async def blend_today(interaction: discord.Interaction, level: str):
    client.to_blend = level
    await interaction.response.send_message(f"Blending {level} today.")
    print(f"Blending {level} today.")


@client.tree.command(
    name="randomblend", description="Adds level to list of random blends"
)
@commands.has_any_role(*ROLES)
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
@commands.has_any_role(*ROLES)
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
@commands.has_any_role(*ROLES)
@app_commands.describe(level="Level to blend")
async def force_blend(interaction: discord.Interaction, level: str):
    await blend_level(level)
    await interaction.response.send_message("Blending!")
    print(f"Force blend {level}.")


@client.tree.command(name="viewqueue", description="View levels in queue")
@commands.has_any_role(*ROLES)
async def view_queue(interaction: discord.Interaction):
    db = shelve.open("scheduled")
    message = "\n".join(f"{k}: {v}" for k, v in sorted(dict(db).items()))
    await interaction.response.send_message(message)


@client.tree.command(name="viewrandom", description="View levels in random")
@commands.has_any_role(*ROLES)
async def view_random(interaction: discord.Interaction):
    with open("random.txt", "r") as f:
        await interaction.response.send_message(f.read())


@tasks.loop(time=BLEND_TIME)
async def get_blend():
    # Check if there's a blend queued using the blend_today command
    if client.to_blend is not None:
        await blend_level(client.to_blend)
        client.to_blend = None
        return

    # Check if there's a blend scheduled for today
    today = datetime.datetime.now(datetime.UTC).today()
    today_str = today.strftime("%m %d")
    db = shelve.open("scheduled")
    if today_str in db:
        await blend_level(db[today_str])
        del db[today_str]
        return

    # Otherwise, blend a random level
    levels = open("random.txt").read().splitlines()
    print(levels)
    await blend_level(levels.pop(random.randrange(len(levels))))
    with open("random.txt", "w") as f:
        for level in levels:
            f.write(f"{level}\n")


def parse_level_id(level_url: str) -> str:
    """
    Grabs the level id from a codex.rhythm.cafe download URL.
    Expects the input URL to look like
    https://codex.rhythm.cafe/cool-name-ABCdef123asdf.rdzip
    """
    parsed_url = urllib.parse.urlparse(level_url)
    if parsed_url.hostname != "codex.rhythm.cafe":
        raise ValueError(
            f"Unknown hostname: '{parsed_url.hostname}', "
            + "expected 'codex.rhythm.cafe'"
        )

    return parsed_url.path.removeprefix("/").removesuffix(".rdzip")


def embed_truncate(string: str) -> str:
    """
    Truncates the given input string to be the maximum length allowed by
    discord.Embed.add_field().
    """
    return (string[:253] + "...") if len(string) > 256 else string


async def blend_level(level: str):
    print(f"Blending {level} at {datetime.datetime.now()}")

    level_id = parse_level_id(level)
    cafe_url = (
        f"https://api.rhythm.cafe/datasette/orchard/level/{level_id}.json?_shape=array"
    )

    async with aiohttp.ClientSession() as session:
        async with session.get(cafe_url) as r:
            if r.status == 404:
                raise Exception(f"Failed to find level with id '{level_id}'.")
            elif r.status != 200:
                raise Exception("Failed to fetch level metadata from rhythm.cafe.")

            json_array: list[dict[str, Any]] = await r.json()
            metadata = json_array[0]

        authors_list = json.loads(metadata["authors"])
        tags_list = (f"**[{tag}]**" for tag in json.loads(metadata["tags"]))

        authors = embed_truncate(", ".join(authors_list))
        tags = embed_truncate(", ".join(tags_list))

        if metadata["single_player"] == 1 and metadata["two_player"] == 1:
            player_display = "1P + 2P"
        elif metadata["single_player"] == 1:
            player_display = "1P"
        elif metadata["two_player"] == 1:
            player_display = "2P"
        else:
            raise Exception("Level somehow doesn't support 1P nor 2P!")

        match metadata["difficulty"]:
            case 0:
                difficulty = "Easy"
            case 1:
                difficulty = "Medium"
            case 2:
                difficulty = "Tough"
            case 3:
                difficulty = "Very Tough"
            case _:
                raise Exception(
                    f"Unknown level metadata difficulty: {metadata['difficulty']}"
                )

        timestamp = (
            datetime.datetime.now(datetime.UTC).today().strftime("%A, %B %d, %Y")
        )

        embed = discord.Embed(color=discord.Color.purple())
        embed.set_author(name=f"Daily Blend: {timestamp}")

        embed.add_field(
            name="Level",
            value=f"{metadata['artist']} - {metadata['song']}",
            inline=True,
        )
        embed.add_field(name="Creator", value=authors, inline=True)

        if "description" in metadata and metadata["description"]:
            embed.add_field(
                name="Description",
                value=embed_truncate(metadata["description"]),
                inline=False,
            )

        embed.add_field(name="Tags", value=tags, inline=False)
        embed.add_field(name="Modes", value=player_display, inline=True)
        embed.add_field(name="Difficulty", value=difficulty, inline=True)
        embed.add_field(
            name="Download", value=f"[Link]({metadata['url2']})", inline=True
        )
        embed.set_image(url=metadata["image"])

        bottom_embed = discord.Embed(
            description="The Daily Blend Café is like a book club for custom levels! "
            + "Play the daily level and post your score (enable Detailed Level Results in Advanced Settings), "
            + "and leave a comment with what you liked about the level!",
        )
        bottom_embed.set_author(name="About the Daily Blend Café")

        webhook = discord.Webhook.from_url(CONFIG.blend_webhook_url, session=session)
        await webhook.send(embeds=[embed, bottom_embed])


if __name__ == "__main__":
    client.run(CONFIG.token)
