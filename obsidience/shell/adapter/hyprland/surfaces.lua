-- The one Surface identity map, read from surface-layout.json at config load.
-- The installation copy under $XDG_CONFIG_HOME/obsidience-shell wins; the
-- repository default seeds it. A Surface names its monitor by Hyprland
-- description (EDID make, model and serial as `hyprctl -j monitors` reports
-- it), matched as a prefix like the native `desc:` selector; its `output`
-- connector is only the fallback. obsidience/shell/surface_identity.py applies
-- the same rule outside the compositor.

local HERE = debug.getinfo(1, "S").source:match("^@(.*/)") or "./"
local DEFAULT_PATH = HERE .. "../../state/initial-surface-layout.json"
local SURFACE_IDS = { samsung = true, ["usb-c"] = true, ["dp-4"] = true }

local function config_path()
    local config = os.getenv("XDG_CONFIG_HOME")
    if not config or config == "" then
        config = (os.getenv("HOME") or "") .. "/.config"
    end
    return config .. "/obsidience-shell/surface-layout.json"
end

-- A small strict JSON reader for this configuration file; null reads as nil.
local function decode(text)
    local position = 1
    local escapes = {
        ['"'] = '"', ["\\"] = "\\", ["/"] = "/",
        b = "\b", f = "\f", n = "\n", r = "\r", t = "\t",
    }

    local function fail()
        error("invalid JSON at byte " .. position, 0)
    end

    local function skip()
        position = text:find("[^ \t\r\n]", position) or #text + 1
    end

    local function string_value()
        local parts = {}
        position = position + 1
        while true do
            local stop = text:find('["\\]', position)
            if not stop then
                fail()
            end
            parts[#parts + 1] = text:sub(position, stop - 1)
            position = stop + 1
            if text:sub(stop, stop) == '"' then
                return table.concat(parts)
            end
            local escape = text:sub(position, position)
            if escape == "u" then
                local hex = text:match("^%x%x%x%x", position + 1)
                if not hex then
                    fail()
                end
                parts[#parts + 1] = utf8.char(tonumber(hex, 16))
                position = position + 5
            elseif escapes[escape] then
                parts[#parts + 1] = escapes[escape]
                position = position + 1
            else
                fail()
            end
        end
    end

    local value

    local function members(close, read)
        position = position + 1
        skip()
        if text:sub(position, position) == close then
            position = position + 1
            return
        end
        while true do
            read()
            skip()
            local separator = text:sub(position, position)
            position = position + 1
            if separator == close then
                return
            elseif separator ~= "," then
                fail()
            end
        end
    end

    value = function()
        skip()
        local first = text:sub(position, position)
        if first == "{" then
            local object = {}
            members("}", function()
                skip()
                if text:sub(position, position) ~= '"' then
                    fail()
                end
                local key = string_value()
                skip()
                if text:sub(position, position) ~= ":" then
                    fail()
                end
                position = position + 1
                object[key] = value()
            end)
            return object
        elseif first == "[" then
            local array, count = {}, 0
            members("]", function()
                count = count + 1
                array[count] = value()
            end)
            return array
        elseif first == '"' then
            return string_value()
        end
        if text:sub(position, position + 3) == "true" then
            position = position + 4
            return true
        elseif text:sub(position, position + 4) == "false" then
            position = position + 5
            return false
        elseif text:sub(position, position + 3) == "null" then
            position = position + 4
            return nil
        end
        local number = text:match("^-?%d+%.?%d*[eE]?[-+]?%d*", position)
        if not number or not tonumber(number) then
            fail()
        end
        position = position + #number
        return tonumber(number)
    end

    local result = value()
    skip()
    if position <= #text then
        fail()
    end
    return result
end

local function identities_from(record)
    if type(record) ~= "table" or type(record.surfaces) ~= "table" then
        return nil
    end
    local identities, seen = {}, {}
    for _, surface in ipairs(record.surfaces) do
        if type(surface) ~= "table" then
            return nil
        end
        local output, description = surface.output, surface.description or ""
        if not SURFACE_IDS[surface.id] or seen[surface.id]
                or type(output) ~= "string" or #output > 64
                or (output ~= "" and not output:match("^[%w._-]+$"))
                or type(description) ~= "string" or #description > 256 then
            return nil
        end
        seen[surface.id] = true
        identities[#identities + 1] = {
            id = surface.id,
            output = output,
            -- Hyprland trims a `desc:` selector the same way.
            description = description:match("^%s*(.-)%s*$"),
        }
    end
    return #identities == 3 and identities or nil
end

local function load()
    for _, path in ipairs({ config_path(), DEFAULT_PATH }) do
        local file = io.open(path, "r")
        if file then
            local text = file:read("a")
            file:close()
            local ok, record = pcall(decode, text or "")
            local identities = ok and identities_from(record)
            if identities then
                return identities
            end
        end
    end
    return {}
end

local M = { identities = load() }

local function described(description, identity)
    return identity.description ~= ""
        and description:sub(1, #identity.description) == identity.description
end

function M.find(surface)
    for _, identity in ipairs(M.identities) do
        if identity.id == surface then
            return identity
        end
    end
    return nil
end

-- The native selector for a Surface: its description, else its connector.
function M.selector(surface)
    local identity = M.find(surface)
    if not identity then
        return nil
    end
    if identity.description ~= "" then
        return "desc:" .. identity.description
    end
    return identity.output ~= "" and identity.output or nil
end

-- The Surface a live monitor belongs to, or nil.
function M.surface_for(monitor)
    if not monitor then
        return nil
    end
    local description = monitor.description or ""
    for _, identity in ipairs(M.identities) do
        if described(description, identity) then
            return identity.id
        end
    end
    for _, identity in ipairs(M.identities) do
        if identity.output ~= "" and identity.output == monitor.name then
            -- A connector never claims a Surface whose own monitor is present elsewhere.
            if identity.description ~= "" then
                for _, other in ipairs(hl.get_monitors()) do
                    if other.name ~= monitor.name and described(other.description or "", identity) then
                        return nil
                    end
                end
            end
            return identity.id
        end
    end
    return nil
end

return M
