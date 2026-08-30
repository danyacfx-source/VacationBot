import datetime
import logging

import aiohttp.web
import discord

import config


def api_check_token(request):
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {config.API_TOKEN}"


async def api_handle_status(request):
    if not api_check_token(request):
        return aiohttp.web.json_response({"error": "Unauthorized"}, status=401)
    bot = request.app["bot"]
    uptime = datetime.datetime.utcnow() - bot.launch_time if hasattr(bot, "launch_time") else None
    try:
        latency_ms = round(bot.latency * 1000)
    except (OverflowError, ValueError, TypeError):
        latency_ms = None
    return aiohttp.web.json_response({
        "status": "online",
        "latency_ms": latency_ms,
        "guilds": len(bot.guilds),
        "users": len(bot.users),
        "commands": len(bot.tree.get_commands()),
        "uptime_seconds": int(uptime.total_seconds()) if uptime else 0
    })


async def api_handle_restart(request):
    if not api_check_token(request):
        return aiohttp.web.json_response({"error": "Unauthorized"}, status=401)
    bot = request.app["bot"]
    resp = aiohttp.web.json_response({"message": "Restarting..."})
    await resp.prepare(request)
    await bot.close()


async def api_handle_stop(request):
    if not api_check_token(request):
        return aiohttp.web.json_response({"error": "Unauthorized"}, status=401)
    bot = request.app["bot"]
    resp = aiohttp.web.json_response({"message": "Stopped"})
    await resp.prepare(request)
    bot._shutdown_requested = True
    await bot.close()


async def api_handle_send(request):
    if not api_check_token(request):
        return aiohttp.web.json_response({"error": "Unauthorized"}, status=401)
    bot = request.app["bot"]
    try:
        data = await request.json()
    except Exception:
        return aiohttp.web.json_response({"error": "Invalid JSON"}, status=400)
    channel_id = data.get("channel_id")
    message = data.get("message", "")
    if not channel_id or not message:
        return aiohttp.web.json_response({"error": "channel_id and message required"}, status=400)
    try:
        ch = bot.get_channel(int(channel_id))
        if not ch:
            return aiohttp.web.json_response({"error": f"Channel {channel_id} not found"}, status=404)
        await ch.send(message)
        return aiohttp.web.json_response({"ok": True, "channel": str(ch)})
    except Exception as e:
        return aiohttp.web.json_response({"error": str(e)}, status=500)


async def api_handle_commands(request):
    if not api_check_token(request):
        return aiohttp.web.json_response({"error": "Unauthorized"}, status=401)
    bot = request.app["bot"]
    cmds = [{"name": c.name, "description": getattr(c, "description", "")} for c in bot.tree.get_commands()]
    return aiohttp.web.json_response({"commands": cmds})


async def api_handle_send_embed(request):
    if not api_check_token(request):
        return aiohttp.web.json_response({"error": "Unauthorized"}, status=401)
    bot = request.app["bot"]
    try:
        data = await request.json()
    except Exception:
        return aiohttp.web.json_response({"error": "Invalid JSON"}, status=400)
    channel_id = data.get("channel_id")
    if not channel_id:
        return aiohttp.web.json_response({"error": "channel_id required"}, status=400)
    try:
        ch = bot.get_channel(int(channel_id))
        if not ch:
            return aiohttp.web.json_response({"error": f"Channel {channel_id} not found"}, status=404)
        embeds_data = data.get("embeds", [])
        embeds = []
        for ed in embeds_data:
            e = discord.Embed()
            if "title" in ed:
                e.title = ed["title"]
            if "description" in ed:
                e.description = ed["description"]
            if "color" in ed:
                e.color = discord.Color(ed["color"])
            if "footer" in ed:
                e.set_footer(text=ed["footer"])
            embeds.append(e)
        await ch.send(embeds=embeds)
        return aiohttp.web.json_response({"ok": True})
    except Exception as e:
        return aiohttp.web.json_response({"error": str(e)}, status=500)


async def api_handle_deploy_vacation_panel(request):
    if not api_check_token(request):
        return aiohttp.web.json_response({"error": "Unauthorized"}, status=401)
    bot = request.app["bot"]
    try:
        data = await request.json()
    except Exception:
        return aiohttp.web.json_response({"error": "Invalid JSON"}, status=400)
    channel_id = data.get("channel_id")
    if not channel_id:
        return aiohttp.web.json_response({"error": "channel_id required"}, status=400)
    try:
        import sys, os
        import json as _json
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from helpers import load_vacations, build_info_panel_embed, build_request_panel_embed
        from cogs.vacations import RequestPanelView
        ch = bot.get_channel(int(channel_id))
        if not ch:
            return aiohttp.web.json_response({"error": f"Channel {channel_id} not found"}, status=404)

        info_embed = build_info_panel_embed(load_vacations())
        info_msg = await ch.send(embed=info_embed)

        request_embed = build_request_panel_embed()
        view = RequestPanelView()
        request_msg = await ch.send(embed=request_embed, view=view)

        vacations = load_vacations()
        raw = {}
        if os.path.exists("vacations.json"):
            with open("vacations.json", "r", encoding="utf-8") as f:
                raw = _json.load(f)
        raw["__panel__"] = {
            "channel_id": int(channel_id),
            "info_message_id": info_msg.id,
            "request_message_id": request_msg.id,
        }
        with open("vacations.json", "w", encoding="utf-8") as f:
            _json.dump(raw, f, ensure_ascii=False, indent=4)

        return aiohttp.web.json_response({
            "ok": True,
            "info_message_id": str(info_msg.id),
            "request_message_id": str(request_msg.id),
        })
    except Exception as e:
        return aiohttp.web.json_response({"error": str(e)}, status=500)


async def api_handle_search_members(request):
    if not api_check_token(request):
        return aiohttp.web.json_response({"error": "Unauthorized"}, status=401)
    bot = request.app["bot"]
    query = request.query.get("q", "").lower()
    all_mode = request.query.get("all", "") == "1"
    results = []
    for guild in bot.guilds:
        for member in guild.members:
            if all_mode or (query and (query in member.name.lower() or query in member.display_name.lower())):
                results.append({
                    "id": str(member.id),
                    "name": member.name,
                    "display_name": member.display_name,
                })
                if not all_mode and len(results) >= 50:
                    break
    return aiohttp.web.json_response({"results": results[:500]})


async def start_api(bot):
    api_app = aiohttp.web.Application()
    api_app["bot"] = bot
    api_app.router.add_get("/api/status", api_handle_status)
    api_app.router.add_post("/api/restart", api_handle_restart)
    api_app.router.add_post("/api/stop", api_handle_stop)
    api_app.router.add_post("/api/send", api_handle_send)
    api_app.router.add_get("/api/commands", api_handle_commands)
    api_app.router.add_get("/api/search_members", api_handle_search_members)
    api_app.router.add_post("/api/send_embed", api_handle_send_embed)
    api_app.router.add_post("/api/deploy_vacation_panel", api_handle_deploy_vacation_panel)

    runner = aiohttp.web.AppRunner(api_app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "0.0.0.0", config.API_PORT)
    await site.start()
    logging.info("API сервер запущен на порту %s", config.API_PORT)
