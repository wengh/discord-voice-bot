from workers import Response, handler

@handler
async def on_fetch(request, env, ctx):
    url = request.url
    key = url.split("/kv/")[-1] if "/kv/" in url else None

    if not key:
        return Response("Missing key", status=400)

    if request.method == "PUT":
        value = await request.text()
        if not value:
            return Response("Missing value in request body", status=400)
        await env.STORAGE_KV.put(key, value)
        return Response(f"Key '{key}' set successfully")

    if request.method == "GET":
        value = await env.STORAGE_KV.get(key)
        if value is None:
            return Response(f"Key '{key}' not found", status=404)
        return Response(value)

    return Response("Method Not Allowed", status=405)
