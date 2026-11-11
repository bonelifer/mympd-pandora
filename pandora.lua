-- {"name":"Pandora","file":"","version":0,"order":1,"arguments":[]}
local service = "http://pandora:8080"
local station = mympd_arguments.station

if station ~= nil then
    if type(station) ~= "string" or not station:match("^[%w_-]+$") then
        return "Invalid Pandora station ID"
    end
    local rc, result = mympd.api("MYMPD_API_QUEUE_APPEND_URIS", {
        uris = {service .. "/stream/" .. station},
        play = true
    })
    if rc ~= 0 then
        return result.message or "Could not start Pandora"
    end
    return "Started Pandora station"
end

local rc, status, _, body = mympd.http_client(
    "GET", service .. "/stations", "", "", false
)
if rc ~= 0 or status ~= 200 then
    return "Could not load Pandora stations"
end
local stations = json.decode(body)
if type(stations) ~= "table" or #stations == 0 then
    return "No Pandora stations found"
end

local ids, names = {}, {}
for _, item in ipairs(stations) do
    ids[#ids + 1] = item.id
    names[#names + 1] = item.name
end
return mympd.dialog("Pandora", {{
    name = "station",
    type = "select",
    value = ids,
    displayValue = names,
    defaultValue = ids[1]
}}, "Pandora")
