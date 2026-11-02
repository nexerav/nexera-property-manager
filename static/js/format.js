// The only rand format in the browser. Must match labels.format_zar in Python:
// R 8,500.00 with a comma for thousands and a dot for cents.
function formatZar(value) {
    const amount = Number(value);
    const number = Number.isFinite(amount) ? amount : 0;
    const sign = number < 0 ? "-" : "";
    const parts = Math.abs(number).toFixed(2).split(".");
    const whole = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return "R " + sign + whole + "." + parts[1];
}
