-- Project the Obsidience workspace grid onto native Hyprland windows.

local GAP = 5
-- Matches general.gaps_in. Each internal logical cut belongs to a window,
-- while Hyprland renders 2 px after the cut and 3 px before it as empty space.
local NATIVE_GAP_START = 2
-- The fastest supported motion is 50 px over 60 s at 1.1x seam pacing.
-- One second therefore moves a seam by at most one rounded logical pixel.
local OLED_TICK_MS = 1000
local OLED_MIN_TILE_SIZE = 1
local OLED_GLOW_ACTIVE = {
    "rgba(02060c00)",
    "rgba(164e6310)",
    "rgba(22d3ee18)",
    "rgba(67e8f933)",
    "rgba(a5f3fc18)",
    "rgba(22d3ee10)",
    "rgba(02060c00)",
    "rgba(02060c00)",
    "rgba(02060c00)",
}
local OLED_GLOW_INACTIVE = {
    "rgba(02060c00)",
    "rgba(102a3508)",
    "rgba(164e6310)",
    "rgba(22d3ee20)",
    "rgba(67e8f912)",
    "rgba(164e6308)",
    "rgba(02060c00)",
    "rgba(02060c00)",
    "rgba(02060c00)",
}
local OLED_BORDER_ACTIVE = {
    "rgba(102a3518)",
    "rgba(164e6322)",
    "rgba(22d3ee38)",
    "rgba(a5f3fc8c)",
    "rgba(67e8f938)",
    "rgba(164e6322)",
    "rgba(102a3518)",
    "rgba(102a3518)",
    "rgba(102a3518)",
}
local OLED_BORDER_INACTIVE = {
    "rgba(102a3510)",
    "rgba(164e6318)",
    "rgba(22d3ee28)",
    "rgba(67e8f940)",
    "rgba(22d3ee28)",
    "rgba(164e6318)",
    "rgba(102a3510)",
    "rgba(102a3510)",
    "rgba(102a3510)",
}
local DEFAULT_GRIDS = {
    ["HDMI-A-1"] = { surface = "samsung", columns = 8, rows = 2 },
    ["DP-8"] = { surface = "usb-c", columns = 3, rows = 2 },
    ["HDMI-A-2"] = { surface = "dp-4", columns = 4, rows = 1 },
}

local grid_overrides = {}
local contexts = {}
local transfers = {}
local last_placed = {}

local settings = {
    manual_limit_percent = 25,
    oled_enabled = false,
    oled_shift_px = 32,
    oled_duration_seconds = 3600,
    oled_glow_rotation_hours = 3,
    session_locked = false,
}

local oled_motion = {
    active_seconds = 0,
    seam_progress = 0,
    glow_angle = 0,
    glow_configured = false,
    last_glow_minute = nil,
}
local oled_timer = nil

local function rounded(value)
    return math.floor(value + 0.5)
end

local function clamped(value, minimum, maximum)
    return math.max(minimum, math.min(maximum, value))
end

local function whole_number(value, minimum, maximum)
    return value ~= nil
        and value == math.floor(value)
        and value >= minimum
        and value <= maximum
end

local function target_id(target)
    local window = target.window
    return window and tostring(window.stable_id) or "group:" .. tostring(target.index)
end

local function normalized_address(value)
    if value == nil then
        return nil
    end
    local address = string.lower(tostring(value))
    return address:match("^0x[0-9a-f]+$") and address or nil
end

local function target_by_address(ctx, address)
    local requested = normalized_address(address)
    if not requested then
        return nil
    end
    for _, target in ipairs(ctx.targets) do
        local window = target.window
        if window and normalized_address(window.address) == requested then
            return target
        end
    end
    return nil
end

local function target_grid(target)
    local window = target.window
    local monitor = window and window.monitor
    local defaults = monitor and DEFAULT_GRIDS[monitor.name]
    if not defaults then
        return nil
    end
    local override = grid_overrides[defaults.surface]
    return override or defaults
end

local function context_id(target, grid)
    local window = target.window
    local workspace = window and window.workspace
    return grid.surface .. ":" .. tostring(workspace and workspace.id or 0)
end

local function bounds(grid, left, top, right, bottom)
    return {
        surface = grid.surface,
        columns = grid.columns,
        rows = grid.rows,
        left = left,
        top = top,
        right = right,
        bottom = bottom,
    }
end

local function adapt(value, grid)
    if value.columns == grid.columns and value.rows == grid.rows then
        value.surface = grid.surface
        return value
    end
    local left = clamped(rounded(value.left * grid.columns / value.columns), 0, grid.columns - 1)
    local top = clamped(rounded(value.top * grid.rows / value.rows), 0, grid.rows - 1)
    local right = clamped(rounded(value.right * grid.columns / value.columns), left + 1, grid.columns)
    local bottom = clamped(rounded(value.bottom * grid.rows / value.rows), top + 1, grid.rows)
    return bounds(grid, left, top, right, bottom)
end

local function infer(ctx, target, grid)
    local area = ctx.area
    local box = target.box
    if not box or area.w <= 0 or area.h <= 0 or box.w <= 0 or box.h <= 0 then
        return nil
    end
    local left = clamped(rounded((box.x - area.x) * grid.columns / area.w), 0, grid.columns - 1)
    local top = clamped(rounded((box.y - area.y) * grid.rows / area.h), 0, grid.rows - 1)
    local right = clamped(rounded((box.x + box.w - area.x) * grid.columns / area.w), left + 1, grid.columns)
    local bottom = clamped(rounded((box.y + box.h - area.y) * grid.rows / area.h), top + 1, grid.rows)
    return bounds(grid, left, top, right, bottom)
end

local function same_box(left, right)
    return left and right
        and rounded(left.x) == rounded(right.x)
        and rounded(left.y) == rounded(right.y)
        and rounded(left.w) == rounded(right.w)
        and rounded(left.h) == rounded(right.h)
end

local function first_free(placements, grid)
    for row = 0, grid.rows - 1 do
        for column = 0, grid.columns - 1 do
            local occupied = false
            for _, value in pairs(placements) do
                if column >= value.left and column < value.right
                        and row >= value.top and row < value.bottom then
                    occupied = true
                    break
                end
            end
            if not occupied then
                return bounds(grid, column, row, column + 1, row + 1)
            end
        end
    end
    return bounds(grid, 0, 0, 1, 1)
end

local function span_for(extent, count, wanted)
    -- gaps_out has already been removed from the Hyprland work area.
    local usable = extent - GAP * (count - 1)
    local best, difference = 1, math.huge
    for span = 1, count do
        local size = rounded(span * usable / count) + (span - 1) * GAP
        local candidate = math.abs(size - wanted)
        if candidate < difference then
            best, difference = span, candidate
        end
    end
    return best
end

local function transferred(ctx, transfer, grid)
    if transfer.bounds then
        return adapt(transfer.bounds, grid)
    end
    local width = span_for(ctx.area.w, grid.columns, transfer.width)
    local height = span_for(ctx.area.h, grid.rows, transfer.height)
    if transfer.edge == nil then
        local left = rounded((grid.columns - width) / 2)
        local top = rounded((grid.rows - height) / 2)
        return bounds(grid, left, top, left + width, top + height)
    end
    local left = clamped(rounded(transfer.ratio * grid.columns - width / 2), 0, grid.columns - width)
    local top = clamped(rounded(transfer.ratio * grid.rows - height / 2), 0, grid.rows - height)
    if transfer.edge == "left" then
        left = 0
    elseif transfer.edge == "right" then
        left = grid.columns - width
    elseif transfer.edge == "top" then
        top = 0
    else
        top = grid.rows - height
    end
    return bounds(grid, left, top, left + width, top + height)
end

local function cut_offset(cuts, index, count)
    if index <= 0 or index >= count then
        return 0
    end
    return cuts[index] or 0
end

local function y_cut_offset(state, index, column, rows)
    if index <= 0 or index >= rows then
        return 0
    end
    local segments = state.y_cuts[index]
    if type(segments) == "number" then
        return segments
    end
    return type(segments) == "table" and (segments[column] or 0) or 0
end

local function y_component(state, grid, cut, left, right)
    local first = clamped(left, 0, grid.columns - 1)
    local last = clamped(right, first + 1, grid.columns)
    local changed = true
    while changed do
        changed = false
        for _, value in pairs(state.placements) do
            if (value.top == cut or value.bottom == cut)
                    and value.left < last and value.right > first then
                local next_first = math.min(first, value.left)
                local next_last = math.max(last, value.right)
                if next_first ~= first or next_last ~= last then
                    first, last = next_first, next_last
                    changed = true
                end
            end
        end
    end
    return first, last
end

local function normalize_y_cuts(state, grid)
    for cut = 1, grid.rows - 1 do
        local existing = state.y_cuts[cut]
        local legacy = type(existing) == "number" and existing or nil
        if type(existing) ~= "table" then
            existing = {}
            state.y_cuts[cut] = existing
        end
        local column = 0
        while column < grid.columns do
            local first, last = y_component(
                state, grid, cut, column, column + 1)
            local value = legacy
            if value == nil then
                for candidate = first, last - 1 do
                    if existing[candidate] ~= nil then
                        value = existing[candidate]
                        break
                    end
                end
            end
            value = value or 0
            for candidate = first, last - 1 do
                existing[candidate] = value
            end
            column = last
        end
    end
    for cut in pairs(state.y_cuts) do
        if type(cut) == "number" and (cut <= 0 or cut >= grid.rows) then
            state.y_cuts[cut] = nil
        end
    end
end

local function y_span_offset(state, index, left, rows)
    return y_cut_offset(state, index, left, rows)
end

local function cell_extent(extent, count, index)
    local usable = extent - GAP * (count - 1)
    return rounded((index + 1) * usable / count) - rounded(index * usable / count)
end

local function reset_cuts_for_grid(state, grid)
    if state.cut_columns == grid.columns and state.cut_rows == grid.rows then
        return
    end
    state.x_cuts = {}
    state.y_cuts = {}
    state.cut_columns = grid.columns
    state.cut_rows = grid.rows
end

local function clamped_cut(cuts, index, count, extent, candidate)
    if settings.manual_limit_percent == 0 or index <= 0 or index >= count then
        return cut_offset(cuts, index, count)
    end

    local before = cell_extent(extent, count, index - 1)
    local after = cell_extent(extent, count, index)
    local before_allowance = math.floor(before * settings.manual_limit_percent / 100)
    local after_allowance = math.floor(after * settings.manual_limit_percent / 100)
    local previous = cut_offset(cuts, index - 1, count)
    local following = cut_offset(cuts, index + 1, count)
    local minimum = math.max(previous - before_allowance, following - after_allowance)
    local maximum = math.min(previous + before_allowance, following + after_allowance)
    if minimum > maximum then
        return cut_offset(cuts, index, count)
    end
    return clamped(candidate, minimum, maximum)
end

local function axis_boundary(
        origin, extent, count, index, manual_offset, oled_offset)
    if index <= 0 then
        return origin
    end
    if index >= count then
        return origin + extent
    end
    local usable = extent - GAP * (count - 1)
    return origin + rounded(index * usable / count) + index * GAP
        - NATIVE_GAP_START + manual_offset + oled_offset
end

local function seam_hash(value)
    local hash = 216613626
    for index = 1, #value do
        hash = (hash * 131 + value:byte(index)) % 2147483647
    end
    return hash
end

local function triangle_position(value)
    local phase = value % 4
    if phase < 1 then
        return phase
    end
    if phase < 3 then
        return 2 - phase
    end
    return phase - 4
end

local function seam_position(key)
    local hash = seam_hash(key)
    -- Every seam starts on its manual baseline. A multiplied hash slot spreads
    -- sequential seam names across the full pacing range; its parity gives
    -- neighboring seams deterministic opposite travel where possible.
    local speed_slot = (hash * 48271) % 201
    local direction = speed_slot % 2 == 0 and 1 or -1
    local speed = 0.9 + speed_slot / 1000
    return triangle_position(direction * oled_motion.seam_progress * speed)
end

local function safe_seam_amplitude(before, after)
    local smaller = math.min(before, after)
    local headroom = math.min(
        before - OLED_MIN_TILE_SIZE,
        after - OLED_MIN_TILE_SIZE)
    -- Each cell can receive two independently moving seams. Five percent per
    -- side retains at least ninety percent of its manual baseline.
    return math.max(0, math.min(
        settings.oled_shift_px,
        math.floor(smaller * 0.05),
        math.floor(headroom / 2)))
end

local function x_oled_offset(area, state, grid, index)
    if index <= 0 or index >= grid.columns then
        return 0
    end
    local previous = axis_boundary(
        area.x, area.w, grid.columns, index - 1,
        cut_offset(state.x_cuts, index - 1, grid.columns), 0)
    local current = axis_boundary(
        area.x, area.w, grid.columns, index,
        cut_offset(state.x_cuts, index, grid.columns), 0)
    local following = axis_boundary(
        area.x, area.w, grid.columns, index + 1,
        cut_offset(state.x_cuts, index + 1, grid.columns), 0)
    local amplitude = safe_seam_amplitude(
        current - previous,
        following - current)
    return rounded(amplitude * seam_position("x:" .. tostring(index)))
end

local function y_oled_offset(area, state, grid, index, left, right)
    if index <= 0 or index >= grid.rows then
        return 0
    end
    local first, last = y_component(state, grid, index, left, right)
    local amplitude = settings.oled_shift_px
    for column = first, last - 1 do
        local previous = axis_boundary(
            area.y, area.h, grid.rows, index - 1,
            y_cut_offset(state, index - 1, column, grid.rows), 0)
        local current = axis_boundary(
            area.y, area.h, grid.rows, index,
            y_cut_offset(state, index, column, grid.rows), 0)
        local following = axis_boundary(
            area.y, area.h, grid.rows, index + 1,
            y_cut_offset(state, index + 1, column, grid.rows), 0)
        amplitude = math.min(
            amplitude,
            safe_seam_amplitude(current - previous, following - current))
    end
    local key = table.concat({ "y", index, first, last }, ":")
    return rounded(amplitude * seam_position(key))
end

local function rect_for_bounds(area, value, state)
    local use_oled = settings.oled_enabled and value.surface == "samsung"
    local left_oled = use_oled
        and x_oled_offset(area, state, value, value.left) or 0
    local right_oled = use_oled
        and x_oled_offset(area, state, value, value.right) or 0
    local top_oled = use_oled
        and y_oled_offset(
            area, state, value, value.top, value.left, value.right) or 0
    local bottom_oled = use_oled
        and y_oled_offset(
            area, state, value, value.bottom, value.left, value.right) or 0
    local x = axis_boundary(
        area.x, area.w, value.columns, value.left,
        cut_offset(state.x_cuts, value.left, value.columns), left_oled)
    local y = axis_boundary(
        area.y, area.h, value.rows, value.top,
        y_span_offset(state, value.top, value.left, value.rows), top_oled)
    local right = axis_boundary(
        area.x, area.w, value.columns, value.right,
        cut_offset(state.x_cuts, value.right, value.columns), right_oled)
    local bottom = axis_boundary(
        area.y, area.h, value.rows, value.bottom,
        y_span_offset(state, value.bottom, value.left, value.rows), bottom_oled)
    return { x = x, y = y, w = right - x, h = bottom - y }
end

local function sync_context(ctx)
    local first = ctx.targets[1]
    local grid = first and target_grid(first)
    if not grid then
        return nil, nil
    end
    local key = context_id(first, grid)
    local state = contexts[key]
    local fresh = state == nil
    if fresh then
        state = { placements = {}, x_cuts = {}, y_cuts = {} }
        contexts[key] = state
    end
    reset_cuts_for_grid(state, grid)
    state.ctx = ctx
    state.grid = grid
    local present = {}
    for _, target in ipairs(ctx.targets) do
        local id = target_id(target)
        present[id] = true
        local transfer = transfers[id]
        local value = state.placements[id]
        if transfer and transfer.surface == grid.surface then
            value = transferred(ctx, transfer, grid)
            transfers[id] = nil
        elseif last_placed[id] and not same_box(target.box, last_placed[id]) then
            local candidate = infer(ctx, target, grid)
            if candidate then
                value = candidate
            elseif value then
                value = adapt(value, grid)
            end
        elseif value then
            value = adapt(value, grid)
        elseif fresh then
            value = infer(ctx, target, grid)
        end
        state.placements[id] = value or first_free(state.placements, grid)
    end
    for id in pairs(state.placements) do
        if not present[id] then
            state.placements[id] = nil
        end
    end
    normalize_y_cuts(state, grid)
    return state, grid
end

local function valid_grid(surface, columns, rows)
    return (surface == "samsung" or surface == "usb-c" or surface == "dp-4")
        and columns and columns >= 1 and columns <= 16 and columns == math.floor(columns)
        and rows and rows >= 1 and rows <= 16 and rows == math.floor(rows)
end

local function place_context(ctx)
    local state, grid = sync_context(ctx)
    if not state then
        return
    end

    for _, target in ipairs(ctx.targets) do
        local id = target_id(target)
        local value = state.placements[id]
        if value then
            local box = rect_for_bounds(ctx.area, value, state)
            if last_placed[id] == nil or not same_box(target.box, box) then
                target:place(box)
            end
            last_placed[id] = box
        end
    end
end

local function context_is_current(key, ctx)
    if not ctx or #ctx.targets == 0 then
        return false
    end
    for _, target in ipairs(ctx.targets) do
        local grid = target_grid(target)
        if not grid or context_id(target, grid) ~= key then
            return false
        end
    end
    return true
end

local function context_target_by_address(address)
    local requested = normalized_address(address)
    if not requested then
        return nil, nil
    end
    local found_context, found_target
    for key, state in pairs(contexts) do
        local ctx = state.ctx
        if context_is_current(key, ctx) then
            for _, target in ipairs(ctx.targets) do
                if target.window
                        and normalized_address(target.window.address) == requested then
                    if found_target then
                        return nil, nil
                    end
                    found_context, found_target = ctx, target
                end
            end
        end
    end
    return found_context, found_target
end

local function active_contexts(surface, allow_fullscreen)
    local result, seen = {}, {}
    for key, state in pairs(contexts) do
        local ctx = state.ctx
        if not context_is_current(key, ctx) then
            -- Hyprland does not emit an empty callback when the final target
            -- leaves a workspace. Never reuse that callback on its new Surface.
            state.ctx = nil
        elseif not seen[ctx] then
            for _, target in ipairs(ctx.targets) do
                local window = target.window
                local workspace = window and window.workspace
                local grid = window and target_grid(target)
                if grid and (surface == nil or grid.surface == surface)
                        and workspace and workspace.active == true then
                    seen[ctx] = true
                    if allow_fullscreen or workspace.has_fullscreen ~= true then
                        table.insert(result, ctx)
                    end
                    break
                end
            end
        end
    end
    return result
end

local function refresh_active_contexts(surface, allow_fullscreen)
    for _, ctx in ipairs(active_contexts(surface, allow_fullscreen)) do
        place_context(ctx)
    end
end

local function scale_manual_cuts(old_limit, new_limit)
    if new_limit >= old_limit or old_limit == 0 then
        return
    end
    local ratio = new_limit / old_limit
    for _, state in pairs(contexts) do
        for index, value in pairs(state.x_cuts or {}) do
            state.x_cuts[index] = value * ratio
        end
        for _, segments in pairs(state.y_cuts or {}) do
            if type(segments) == "table" then
                for column, value in pairs(segments) do
                    segments[column] = value * ratio
                end
            end
        end
    end
end

local function reset_oled_motion()
    oled_motion.active_seconds = 0
    oled_motion.seam_progress = 0
    oled_motion.glow_angle = 0
    oled_motion.glow_configured = false
    oled_motion.last_glow_minute = nil
end

local function configure_oled_glow(enabled)
    hl.config({
        general = {
            col = {
                active_border = enabled and {
                    colors = OLED_BORDER_ACTIVE,
                    angle = oled_motion.glow_angle,
                } or "rgba(67e8f966)",
                inactive_border = enabled and {
                    colors = OLED_BORDER_INACTIVE,
                    angle = oled_motion.glow_angle,
                } or "rgb(294b54)",
            },
        },
        decoration = {
            glow = {
                enabled = enabled,
                range = 5,
                render_power = 3,
                color = { colors = OLED_GLOW_ACTIVE, angle = oled_motion.glow_angle },
                color_inactive = {
                    colors = OLED_GLOW_INACTIVE,
                    angle = oled_motion.glow_angle,
                },
            },
        },
    })
    oled_motion.glow_configured = enabled
    oled_motion.last_glow_minute = enabled
        and math.floor(oled_motion.active_seconds / 60) or nil
end

local function oled_tick_ms()
    return OLED_TICK_MS
end

local function active_oled_contexts()
    if settings.session_locked then
        return nil
    end
    local result = active_contexts("samsung", true)
    if #result == 0 then
        return nil
    end
    for _, ctx in ipairs(result) do
        for _, target in ipairs(ctx.targets) do
            local window = target.window
            local monitor = window and window.monitor
            local workspace = window and window.workspace
            if not monitor or monitor.dpms_status ~= true then
                return nil
            end
            if workspace and workspace.active == true
                    and workspace.has_fullscreen == true then
                return nil
            end
        end
    end
    return result
end

local function oled_tick()
    if not settings.oled_enabled then
        if oled_timer then oled_timer:set_enabled(false) end
        return
    end

    local contexts_to_place = active_oled_contexts()
    if not contexts_to_place then
        return
    end

    oled_motion.active_seconds = oled_motion.active_seconds
        + OLED_TICK_MS / 1000
    oled_motion.seam_progress = oled_motion.seam_progress
        + OLED_TICK_MS / 1000 / settings.oled_duration_seconds
    for _, ctx in ipairs(contexts_to_place) do
        place_context(ctx)
    end

    oled_motion.glow_angle = (
        360 * oled_motion.active_seconds
            / (settings.oled_glow_rotation_hours * 3600)) % 360
    local glow_minute = math.floor(oled_motion.active_seconds / 60)
    if not oled_motion.glow_configured
            or glow_minute ~= oled_motion.last_glow_minute then
        configure_oled_glow(true)
    end
end

local function ensure_oled_timer()
    local timeout = oled_tick_ms()
    if not oled_timer then
        oled_timer = hl.timer(oled_tick, { timeout = timeout, type = "repeat" })
    else
        oled_timer:set_timeout(timeout)
        oled_timer:set_enabled(true)
    end
end

local function apply_settings(
        limit_percent, oled_enabled, shift_px, duration_seconds,
        glow_rotation_hours, session_locked)
    local old_limit = settings.manual_limit_percent
    local was_enabled = settings.oled_enabled
    local old_glow_rotation_hours = settings.oled_glow_rotation_hours
    scale_manual_cuts(old_limit, limit_percent)

    settings.manual_limit_percent = limit_percent
    settings.oled_enabled = oled_enabled
    settings.oled_shift_px = shift_px
    settings.oled_duration_seconds = duration_seconds
    settings.oled_glow_rotation_hours = glow_rotation_hours
    settings.session_locked = session_locked

    if not oled_enabled then
        reset_oled_motion()
        if oled_timer then oled_timer:set_enabled(false) end
    else
        if not was_enabled then
            reset_oled_motion()
        end
        ensure_oled_timer()
    end

    if not oled_enabled then
        configure_oled_glow(false)
    elseif active_oled_contexts()
            and (not was_enabled
                or old_glow_rotation_hours ~= glow_rotation_hours) then
        configure_oled_glow(true)
    end
    refresh_active_contexts(nil, false)
end

local function move_shared_cut(state, grid, value, dx, dy, corner, area)
    local moves_left = corner == "left" or corner == "top-left" or corner == "bottom-left"
    local moves_right = corner == "right" or corner == "top-right" or corner == "bottom-right"
    local moves_top = corner == "top" or corner == "top-left" or corner == "top-right"
    local moves_bottom = corner == "bottom" or corner == "bottom-left" or corner == "bottom-right"

    local x_cut, x_delta = nil, dx
    if moves_left then
        if value.left > 0 then
            x_cut = value.left
        elseif value.right < grid.columns then
            x_cut, x_delta = value.right, -dx
        end
    elseif moves_right then
        if value.right < grid.columns then
            x_cut = value.right
        elseif value.left > 0 then
            x_cut, x_delta = value.left, -dx
        end
    end
    if x_cut then
        local current = cut_offset(state.x_cuts, x_cut, grid.columns)
        state.x_cuts[x_cut] = clamped_cut(
            state.x_cuts, x_cut, grid.columns, area.w, current + x_delta)
    end

    local y_cut, y_delta = nil, dy
    if moves_top then
        if value.top > 0 then
            y_cut = value.top
        elseif value.bottom < grid.rows then
            y_cut, y_delta = value.bottom, -dy
        end
    elseif moves_bottom then
        if value.bottom < grid.rows then
            y_cut = value.bottom
        elseif value.top > 0 then
            y_cut, y_delta = value.top, -dy
        end
    end
    if y_cut then
        local first, last = y_component(
            state, grid, y_cut, value.left, value.right)
        local current = y_cut_offset(state, y_cut, first, grid.rows)
        local before = cell_extent(area.h, grid.rows, y_cut - 1)
        local after = cell_extent(area.h, grid.rows, y_cut)
        local before_allowance = math.floor(
            before * settings.manual_limit_percent / 100)
        local after_allowance = math.floor(
            after * settings.manual_limit_percent / 100)
        local minimum, maximum = -math.huge, math.huge
        for column = first, last - 1 do
            local previous = y_cut_offset(
                state, y_cut - 1, column, grid.rows)
            local following = y_cut_offset(
                state, y_cut + 1, column, grid.rows)
            minimum = math.max(
                minimum,
                previous - before_allowance,
                following - after_allowance)
            maximum = math.min(
                maximum,
                previous + before_allowance,
                following + after_allowance)
        end
        if minimum <= maximum then
            local next_value = clamped(current + y_delta, minimum, maximum)
            local segments = state.y_cuts[y_cut]
            if type(segments) ~= "table" then
                segments = {}
                state.y_cuts[y_cut] = segments
            end
            for column = first, last - 1 do
                segments[column] = next_value
            end
        end
    end
end

local provider = {
    recalculate = function(ctx)
        place_context(ctx)
    end,

    resize = function(ctx, target, dx, dy, corner)
        if settings.manual_limit_percent == 0 or type(dx) ~= "number" or type(dy) ~= "number" then
            return
        end
        local state, grid = sync_context(ctx)
        local value = state and state.placements[target_id(target)]
        if not value then
            return
        end
        move_shared_cut(state, grid, value, dx, dy, corner, ctx.area)
    end,

    layout_msg = function(ctx, message)
        local tokens = {}
        for token in message:gmatch("%S+") do
            table.insert(tokens, token)
        end
        if tokens[1] == "grid" then
            local columns, rows = tonumber(tokens[3]), tonumber(tokens[4])
            if #tokens ~= 4 or not valid_grid(tokens[2], columns, rows) then
                return "obsidience: invalid grid"
            end
            grid_overrides[tokens[2]] = {
                surface = tokens[2],
                columns = columns,
                rows = rows,
            }
            return true
        end
        if tokens[1] == "settings" then
            local limit_percent = tonumber(tokens[2])
            local oled_enabled = tonumber(tokens[3])
            local shift_px = tonumber(tokens[4])
            local duration_seconds = tonumber(tokens[5])
            local glow_rotation_hours = tonumber(tokens[6] or "3")
            local session_locked = tonumber(tokens[7])
            if #tokens ~= 7
                    or not whole_number(limit_percent, 0, 25)
                    or not whole_number(oled_enabled, 0, 1)
                    or not whole_number(shift_px, 1, 50)
                    or not whole_number(duration_seconds, 60, 86400)
                    or not whole_number(glow_rotation_hours, 1, 24)
                    or not whole_number(session_locked, 0, 1) then
                return "obsidience: invalid settings"
            end
            apply_settings(
                limit_percent,
                oled_enabled == 1,
                shift_px,
                duration_seconds,
                glow_rotation_hours,
                session_locked == 1)
            return true
        end
        local requested_id = tokens[2]
        local target
        if tokens[1] == "place" or tokens[1] == "place-cancel"
                or tokens[1] == "restore" or tokens[1] == "verify-place" then
            -- Hyprland delivers layout messages to the focused workspace.
            -- Exact effects may address a window on another current workspace.
            ctx, target = context_target_by_address(requested_id)
        else
            target = requested_id and target_by_address(ctx, requested_id)
        end
        if not target then
            return "obsidience: target unavailable"
        end
        if tokens[1] == "verify-place" then
            local columns, rows = tonumber(tokens[4]), tonumber(tokens[5])
            local left, top = tonumber(tokens[6]), tonumber(tokens[7])
            local right, bottom = tonumber(tokens[8]), tonumber(tokens[9])
            if #tokens ~= 9 or not valid_grid(tokens[3], columns, rows)
                    or not whole_number(left, 0, columns)
                    or not whole_number(top, 0, rows)
                    or not whole_number(right, 0, columns)
                    or not whole_number(bottom, 0, rows)
                    or left >= right or top >= bottom then
                return "obsidience: invalid placement verification"
            end
            local grid = target_grid(target)
            local id = target_id(target)
            local state = grid and contexts[context_id(target, grid)]
            local value = state and state.placements[id]
            -- Read the sole layout owner's settled state; do not infer or place.
            if not value or transfers[id]
                    or grid.surface ~= tokens[3]
                    or grid.columns ~= columns or grid.rows ~= rows
                    or value.surface ~= tokens[3]
                    or value.columns ~= columns or value.rows ~= rows
                    or value.left ~= left or value.top ~= top
                    or value.right ~= right or value.bottom ~= bottom
                    or not same_box(target.box, last_placed[id]) then
                return "obsidience: placement not observed"
            end
            return true
        end
        if tokens[1] == "place-cancel" then
            if #tokens ~= 2 then
                return "obsidience: invalid place cancel"
            end
            transfers[target_id(target)] = nil
            return true
        end
        if tokens[1] == "place" then
            local columns, rows = tonumber(tokens[4]), tonumber(tokens[5])
            local has_bounds = #tokens == 9
            local left, top = tonumber(tokens[6]), tonumber(tokens[7])
            local right, bottom = tonumber(tokens[8]), tonumber(tokens[9])
            if (#tokens ~= 5 and not has_bounds)
                    or not valid_grid(tokens[3], columns, rows)
                    or (has_bounds and (
                        not whole_number(left, 0, columns)
                        or not whole_number(top, 0, rows)
                        or not whole_number(right, 0, columns)
                        or not whole_number(bottom, 0, rows)
                        or left >= right or top >= bottom)) then
                return "obsidience: invalid place"
            end
            local destination = {
                surface = tokens[3],
                columns = columns,
                rows = rows,
            }
            grid_overrides[tokens[3]] = destination
            local state, grid = sync_context(ctx)
            if state and grid.surface == tokens[3] then
                if has_bounds then
                    state.placements[target_id(target)] = bounds(
                        destination, left, top, right, bottom)
                    place_context(ctx)
                end
                return true
            end
            transfers[target_id(target)] = {
                surface = tokens[3],
                width = target.box.w,
                height = target.box.h,
                bounds = has_bounds and bounds(
                    destination, left, top, right, bottom) or nil,
            }
            return true
        end
        if tokens[1] == "restore" then
            local columns, rows = tonumber(tokens[4]), tonumber(tokens[5])
            local left, top = tonumber(tokens[6]), tonumber(tokens[7])
            local right, bottom = tonumber(tokens[8]), tonumber(tokens[9])
            if #tokens ~= 9 or not valid_grid(tokens[3], columns, rows)
                    or not whole_number(left, 0, columns)
                    or not whole_number(top, 0, rows)
                    or not whole_number(right, 0, columns)
                    or not whole_number(bottom, 0, rows)
                    or left >= right or top >= bottom then
                return "obsidience: invalid restore"
            end
            grid_overrides[tokens[3]] = {
                surface = tokens[3],
                columns = columns,
                rows = rows,
            }
            local state, grid = sync_context(ctx)
            if not state or grid.surface ~= tokens[3] then
                return "obsidience: target is on another surface"
            end
            state.placements[target_id(target)] = bounds(
                grid, left, top, right, bottom)
            place_context(ctx)
            return true
        end
        if not target.window or target.window.active ~= true then
            return "obsidience: target is not active"
        end
        local id = target_id(target)
        if tokens[1] == "cancel" then
            if #tokens ~= 2 then
                return "obsidience: invalid cancel"
            end
            transfers[id] = nil
            return true
        end
        if tokens[1] == "transfer" then
            local columns, rows = tonumber(tokens[4]), tonumber(tokens[5])
            local edge, ratio = tokens[6], tonumber(tokens[7])
            if #tokens ~= 7 or not valid_grid(tokens[3], columns, rows)
                    or not (edge == "left" or edge == "right" or edge == "top" or edge == "bottom")
                    or not ratio or ratio < 0 or ratio > 1 then
                return "obsidience: invalid transfer"
            end
            grid_overrides[tokens[3]] = { surface = tokens[3], columns = columns, rows = rows }
            transfers[id] = {
                surface = tokens[3],
                width = target.box.w,
                height = target.box.h,
                edge = edge,
                ratio = ratio,
            }
            return true
        end
        local columns, rows = tonumber(tokens[5]), tonumber(tokens[6])
        if #tokens ~= 6 or (tokens[1] ~= "resize" and tokens[1] ~= "translate")
                or not (tokens[3] == "left" or tokens[3] == "right"
                    or tokens[3] == "top" or tokens[3] == "bottom")
                or not valid_grid(tokens[4], columns, rows) then
            return "obsidience: invalid layout command"
        end
        grid_overrides[tokens[4]] = { surface = tokens[4], columns = columns, rows = rows }
        local state, grid = sync_context(ctx)
        local value = state and state.placements[id]
        if not value or grid.surface ~= tokens[4] then
            return "obsidience: target is on another surface"
        end
        value = adapt(value, grid_overrides[tokens[4]])
        local direction = tokens[3]
        if tokens[1] == "translate" then
            local dx = direction == "left" and -1 or direction == "right" and 1 or 0
            local dy = direction == "top" and -1 or direction == "bottom" and 1 or 0
            if value.left + dx >= 0 and value.right + dx <= value.columns
                    and value.top + dy >= 0 and value.bottom + dy <= value.rows then
                value.left, value.right = value.left + dx, value.right + dx
                value.top, value.bottom = value.top + dy, value.bottom + dy
            end
        elseif direction == "left" then
            if value.left > 0 then value.left = value.left - 1
            elseif value.right - value.left > 1 then value.right = value.right - 1 end
        elseif direction == "right" then
            if value.right < value.columns then value.right = value.right + 1
            elseif value.right - value.left > 1 then value.left = value.left + 1 end
        elseif direction == "top" then
            if value.top > 0 then value.top = value.top - 1
            elseif value.bottom - value.top > 1 then value.bottom = value.bottom - 1 end
        elseif direction == "bottom" then
            if value.bottom < value.rows then value.bottom = value.bottom + 1
            elseif value.bottom - value.top > 1 then value.top = value.top + 1 end
        end
        state.placements[id] = value
        return true
    end,
}

hl.layout.register("obsidience", provider)

return provider
