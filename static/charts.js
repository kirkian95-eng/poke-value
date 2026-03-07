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
