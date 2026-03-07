/**
 * Shared Chart.js theme helper for poke-value.
 * Dark theme defaults with consistent color palette.
 */

const CHART_COLORS = {
    gold: '#ffd700',
    blue: '#64b5f6',
    green: '#66bb6a',
    red: '#ef5350',
    purple: '#ce93d8',
    gray: '#78909c',
    // Extended palette for multi-series
    orange: '#ffa726',
    teal: '#4db6ac',
    pink: '#f06292',
    lime: '#aed581',
};

const CHART_PALETTE = [
    CHART_COLORS.gold,
    CHART_COLORS.blue,
    CHART_COLORS.green,
    CHART_COLORS.red,
    CHART_COLORS.purple,
    CHART_COLORS.orange,
    CHART_COLORS.teal,
    CHART_COLORS.pink,
    CHART_COLORS.lime,
    CHART_COLORS.gray,
];

// Dark theme defaults
const DARK_THEME = {
    color: '#b0bec5',
    borderColor: '#0f3460',
    backgroundColor: '#16213e',
};

/**
 * Create a Chart.js chart with dark theme defaults.
 * @param {HTMLCanvasElement|string} ctx - Canvas element or ID
 * @param {string} type - Chart type (bar, line, pie, doughnut, scatter, etc.)
 * @param {object} data - Chart.js data object
 * @param {object} [options] - Chart.js options (merged with theme defaults)
 * @returns {Chart} Chart instance
 */
function createChart(ctx, type, data, options) {
    if (typeof ctx === 'string') {
        ctx = document.getElementById(ctx);
    }

    const defaults = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                labels: { color: DARK_THEME.color },
            },
            tooltip: {
                backgroundColor: '#16213e',
                titleColor: '#ffd700',
                bodyColor: '#e0e0e0',
                borderColor: '#0f3460',
                borderWidth: 1,
            },
        },
        scales: {},
    };

    // Add scale defaults for chart types that use axes
    if (['bar', 'line', 'scatter'].includes(type)) {
        defaults.scales = {
            x: {
                ticks: { color: DARK_THEME.color },
                grid: { color: '#1a2744' },
            },
            y: {
                ticks: { color: DARK_THEME.color },
                grid: { color: '#1a2744' },
            },
        };
    }

    // Deep merge options
    const merged = deepMerge(defaults, options || {});

    return new Chart(ctx, { type, data, options: merged });
}

/**
 * Parse a table cell's text content into a numeric value for sorting.
 * Strips $, commas, %, +, and other formatting.
 * Returns null for empty/missing data (displayed as '-' or '—').
 * Preserves negative signs for proper numeric sorting.
 */
function parseSortVal(text) {
    var v = text.trim()
        .replace(/[$,%+]/g, '')
        .replace(/,/g, '')
        .replace(/promos/g, '')
        .trim();
    if (v === '' || v === '-' || v === '\u2014' || v === '?') return null;
    if (v === 'WIN' || v === 'RIP') return 1;
    if (v === 'LOSE' || v === 'FLIP') return 0;
    if (v === 'EVEN') return 0.5;
    var n = parseFloat(v);
    return isNaN(n) ? null : n;
}

/**
 * Generic table sort handler. Call from onclick="sortTable(col)".
 * Requires a global `sortDir` object and a table with the given ID.
 */
function sortTableById(tableId, col, paired) {
    var table = document.getElementById(tableId);
    var tbody = table.querySelector('tbody');
    var allRows = Array.from(tbody.querySelectorAll('tr'));
    sortDir[col] = !sortDir[col];

    if (paired) {
        // Handle paired rows (main + detail row)
        var pairs = [];
        for (var i = 0; i < allRows.length; i += 2) {
            pairs.push({ main: allRows[i], detail: allRows[i + 1] });
        }
        pairs.sort(function(a, b) {
            var aCell = a.main.children[col];
            var bCell = b.main.children[col];
            var aV = parseSortVal((aCell.dataset.sort || aCell.textContent));
            var bV = parseSortVal((bCell.dataset.sort || bCell.textContent));
            if (aV !== null && bV !== null) return sortDir[col] ? aV - bV : bV - aV;
            if (aV === null && bV === null) return 0;
            if (aV === null) return 1;
            return -1;
        });
        pairs.forEach(function(p) {
            tbody.appendChild(p.main);
            tbody.appendChild(p.detail);
        });
    } else {
        allRows.sort(function(a, b) {
            var aCell = a.children[col];
            var bCell = b.children[col];
            var aV = parseSortVal((aCell.dataset.sort || aCell.textContent));
            var bV = parseSortVal((bCell.dataset.sort || bCell.textContent));
            if (aV !== null && bV !== null) return sortDir[col] ? aV - bV : bV - aV;
            if (aV === null && bV === null) {
                var aT = (aCell.dataset.sort || aCell.textContent).trim();
                var bT = (bCell.dataset.sort || bCell.textContent).trim();
                return sortDir[col] ? aT.localeCompare(bT) : bT.localeCompare(aT);
            }
            if (aV === null) return 1;
            return -1;
        });
        allRows.forEach(function(r) { tbody.appendChild(r); });
    }
}

/** Deep merge two objects (b overrides a). */
function deepMerge(a, b) {
    const result = { ...a };
    for (const key of Object.keys(b)) {
        if (b[key] && typeof b[key] === 'object' && !Array.isArray(b[key]) &&
            a[key] && typeof a[key] === 'object' && !Array.isArray(a[key])) {
            result[key] = deepMerge(a[key], b[key]);
        } else {
            result[key] = b[key];
        }
    }
    return result;
}
