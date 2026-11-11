-- {"name":"PandoraControls","file":"","version":0,"order":0,"arguments":[]}
local service = "http://127.0.0.1:18765"
local args = mympd_arguments
local headers = "Content-Type: application/json\r\nCache-Control: no-store\r\n"
local song_actions = {
    skip = true, love = true, unlove = true, dislike = true,
    tired = true, explain = true, create = true, ["remove-rating"] = true
}
local management_actions = {
    list = true, details = true, search = true, create = true,
    rename = true, delete = true, quickmix = true,
    ["add-seed"] = true, ["remove-seed"] = true, ["remove-rating"] = true
}

if mympd_env.scriptevent ~= "http" then
    return "Pandora controls require an HTTP request"
end

local method, path, payload = "GET", "", ""
if args.manage then
    path = "/manage"
    if args.manage ~= "token" then
        if not management_actions[args.manage] or type(args.payload) ~= "string" then
            return mympd.http_reply(400, headers, '{"error":"Invalid station action"}')
        end
        method = "POST"
        path = path .. "/" .. args.manage
        payload = args.payload
    end
else
    local station = args.station
    if type(station) ~= "string" or not station:match("^[%w_-]+$") then
        return mympd.http_reply(400, headers, '{"error":"Invalid station"}')
    end
    path = "/controls/" .. station
    if args.action then
        local track = args.track
        if not song_actions[args.action] or type(track) ~= "string"
            or #track ~= 32 or not track:match("^[a-f0-9]+$") then
            return mympd.http_reply(400, headers, '{"error":"Invalid Pandora action"}')
        end
        method = "POST"
        path = path .. "/" .. args.action .. "?track=" .. track
    end
end

local rc, status, _, body = mympd.http_client(
    method, service .. path, "Content-Type: application/json\r\n", payload, false
)
if rc ~= 0 and (status == nil or status < 400) then
    return mympd.http_reply(502, headers, '{"error":"Pandora bridge unavailable"}')
end
return mympd.http_reply(status, headers, body)
