const premiumMessage = "Premium feature – contact Nexera Ventures";

const state = {
    period: "month",
    start: "",
    end: "",
    propertyId: "",
    status: "",
    properties: [],
    income: [],
    expenses: [],
    maintenance: [],
    invoices: [],
    settings: {},
    summary: null,
    incomeEdit: null,
    expenseEdit: null,
    propertyEdit: null,
    maintenanceEdit: null,
    invoiceEdit: null,
};

let chart = null;

function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
    }[ch]));
}

function money(value) {
    const amount = Number(value) || 0;
    return "R " + amount.toLocaleString("en-ZA", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
}

function today() {
    const now = new Date();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return `${now.getFullYear()}-${month}-${day}`;
}

function propertyName(id) {
    const match = state.properties.find((item) => item.id === id);
    return match ? match.name : "Unknown property";
}

function notice(message, isError) {
    const box = document.getElementById("notice");
    box.textContent = message;
    box.classList.toggle("error", Boolean(isError));
    box.style.display = message ? "block" : "none";
}

function showPremium() {
    notice(premiumMessage, true);
    window.alert(premiumMessage);
}

async function api(url, options) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
        const response = await fetch(url, { ...(options || {}), signal: controller.signal });
        if (response.status === 401) {
            window.location = "/login";
            throw new Error("Sign in required");
        }
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || "Something went wrong");
        }
        return data;
    } catch (error) {
        if (error.name === "AbortError") {
            throw new Error("The app did not answer. Wait a moment and refresh.");
        }
        throw error;
    } finally {
        clearTimeout(timer);
    }
}

function query(extra) {
    const params = new URLSearchParams();
    params.set("period", state.period);
    if (state.period === "custom") {
        if (state.start) params.set("start", state.start);
        if (state.end) params.set("end", state.end);
    }
    if (state.propertyId) params.set("property_id", state.propertyId);
    if (extra) {
        Object.entries(extra).forEach(([key, value]) => {
            if (value) params.set(key, value);
        });
    }
    return params.toString();
}

function fillPropertySelects() {
    document.querySelectorAll("select[data-properties]").forEach((select) => {
        const current = select.value;
        const blank = select.dataset.blank;
        const options = [];
        if (blank !== undefined) {
            options.push(`<option value="">${esc(blank)}</option>`);
        }
        state.properties.forEach((prop) => {
            options.push(`<option value="${esc(prop.id)}">${esc(prop.name)}</option>`);
        });
        select.innerHTML = options.join("");
        const preferred = select.id === "property-filter" ? state.propertyId : current;
        if ([...select.options].some((option) => option.value === preferred)) {
            select.value = preferred;
        }
    });
}

function showView(name) {
    document.querySelectorAll("[data-view]").forEach((view) => {
        view.hidden = view.dataset.view !== name;
    });
    document.querySelectorAll(".tabs button[data-tab]").forEach((button) => {
        button.classList.toggle("active", button.dataset.tab === name);
    });
    if (name === "overview" && chart) chart.resize();
}

function renderSummary() {
    const data = state.summary || {};
    const net = Number(data.net) || 0;
    document.getElementById("summary-cards").innerHTML = `
        <div class="card"><h3>Income</h3><div class="value">${money(data.income)}</div><div class="hint">Rent ${money(data.rent)} · Other ${money(data.other_income)}</div></div>
        <div class="card"><h3>Expenses</h3><div class="value">${money(data.expenses)}</div><div class="hint">Cash paid in this period</div></div>
        <div class="card"><h3>Net</h3><div class="value ${net < 0 ? "negative" : "positive"}">${money(net)}</div><div class="hint">Income minus expenses</div></div>
        <div class="card"><h3>Properties</h3><div class="value">${data.properties || 0}</div></div>
        <div class="card"><h3>Open maintenance</h3><div class="value">${data.open_maintenance || 0}</div><div class="hint">Not limited to the period</div></div>
    `;
    const jobs = document.getElementById("job-count");
    jobs.textContent = data.open_maintenance ? ` (${data.open_maintenance})` : "";

    const rows = data.by_property || [];
    const canvas = document.getElementById("chart");
    const missing = document.getElementById("chart-missing");
    if (typeof Chart === "undefined") {
        missing.hidden = false;
        missing.textContent = "The chart library did not load. The totals above are still correct.";
        return;
    }
    missing.hidden = true;
    if (chart) chart.destroy();
    chart = new Chart(canvas, {
        type: "bar",
        data: {
            labels: rows.map((row) => row.name),
            datasets: [
                { label: "Income", data: rows.map((row) => row.income), backgroundColor: "#48bb78" },
                { label: "Expenses", data: rows.map((row) => row.expenses), backgroundColor: "#f56565" },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: "bottom" } },
            scales: { y: { beginAtZero: true } },
        },
    });

    const categoryBody = document.querySelector("#category-table tbody");
    const categories = data.by_category || [];
    categoryBody.innerHTML = categories.length
        ? categories.map((row) => `<tr><td>${esc(row.category)}</td><td class="num">${money(row.amount)}</td></tr>`).join("")
        : `<tr><td colspan="2" class="empty">No expenses in this period.</td></tr>`;
}

function renderProperties() {
    const totals = Object.fromEntries((state.summary?.by_property || []).map((row) => [row.id, row]));
    const body = document.querySelector("#property-table tbody");
    if (!state.properties.length) {
        body.innerHTML = `<tr><td colspan="7" class="empty">No properties yet. Add a unit, or keep Company Expenses for overhead.</td></tr>`;
        return;
    }
    body.innerHTML = state.properties.map((prop) => {
        const totalsRow = totals[prop.id] || { income: 0, expenses: 0, net: 0 };
        const rent = prop.monthly_rent == null || prop.monthly_rent === "" ? "—" : money(prop.monthly_rent);
        return `<tr>
            <td>${esc(prop.name)}<div class="hint">${esc(prop.notes || "")}</div></td>
            <td>${esc(prop.kind || "")}</td>
            <td>${esc(prop.address || "")}</td>
            <td class="num">${rent}</td>
            <td class="num">${money(totalsRow.income)}</td>
            <td class="num">${money(totalsRow.expenses)}</td>
            <td class="num">${money(totalsRow.net)}</td>
            <td class="row-actions">
                <button type="button" class="small secondary" data-action="edit-property" data-id="${esc(prop.id)}">Edit</button>
                <button type="button" class="small secondary" data-action="focus-property" data-id="${esc(prop.id)}">Money</button>
                <button type="button" class="small danger" data-action="delete-property" data-id="${esc(prop.id)}">Delete</button>
            </td>
        </tr>`;
    }).join("");
}

function detailText(entry, kind) {
    const parts = [];
    if (kind === "income") {
        parts.push(entry.income_type || "Rent");
        if (entry.recovery_category) parts.push(entry.recovery_category);
        if (entry.tenant) parts.push(entry.tenant);
    } else {
        parts.push(entry.category || "Other");
        if (entry.vendor) parts.push(entry.vendor);
    }
    if (entry.description) parts.push(entry.description);
    return parts.join(" · ");
}

function renderMoney() {
    const rows = [
        ...state.income.map((entry) => ({ ...entry, kind: "income" })),
        ...state.expenses.map((entry) => ({ ...entry, kind: "expense" })),
    ].sort((a, b) => String(b.date).localeCompare(String(a.date)) || String(b.id).localeCompare(String(a.id)));
    const body = document.querySelector("#money-table tbody");
    body.innerHTML = rows.length
        ? rows.map((entry) => `<tr>
            <td>${esc(entry.date)}</td>
            <td>${esc(propertyName(entry.property_id))}</td>
            <td>${entry.kind === "income" ? "Income" : "Expense"}</td>
            <td>${esc(detailText(entry, entry.kind))}</td>
            <td class="num">${money(entry.amount)}</td>
            <td class="row-actions">
                <button type="button" class="small secondary" data-action="edit-${entry.kind}" data-id="${esc(entry.id)}">Edit</button>
                <button type="button" class="small danger" data-action="delete-${entry.kind}" data-id="${esc(entry.id)}">Delete</button>
            </td>
        </tr>`).join("")
        : `<tr><td colspan="6" class="empty">No income or expenses in this period.</td></tr>`;
}

function statusClass(status) {
    if (status === "Done") return "done";
    if (status === "In progress") return "progress";
    return "open";
}

function renderMaintenance() {
    const body = document.querySelector("#maint-table tbody");
    body.innerHTML = state.maintenance.length
        ? state.maintenance.map((entry) => {
            const copied = entry.expense_id ? "In expenses" : "Copy to expenses";
            const cost = entry.cost == null || entry.cost === "" ? "—" : money(entry.cost);
            return `<tr>
                <td>${esc(entry.date)}</td>
                <td>${esc(propertyName(entry.property_id))}</td>
                <td>${esc(entry.issue_type)}<div class="hint">${esc(entry.urgency)}</div></td>
                <td>${esc(entry.description)}${entry.tenant_name ? `<div class="hint">${esc(entry.tenant_name)}</div>` : ""}</td>
                <td>
                    <select data-action="status" data-id="${esc(entry.id)}" aria-label="Status for ${esc(entry.description)}">
                        ${["Open", "In progress", "Done"].map((status) => `<option value="${status}" ${status === entry.status ? "selected" : ""}>${status}</option>`).join("")}
                    </select>
                    <div class="tag ${statusClass(entry.status)}">${esc(entry.status)}</div>
                </td>
                <td class="num">${cost}</td>
                <td class="row-actions">
                    <button type="button" class="small secondary" data-action="edit-maintenance" data-id="${esc(entry.id)}">Edit</button>
                    <button type="button" class="small secondary" data-action="copy-expense" data-id="${esc(entry.id)}" ${entry.cost == null || entry.expense_id ? "disabled" : ""}>${copied}</button>
                    <button type="button" class="small danger" data-action="delete-maintenance" data-id="${esc(entry.id)}">Delete</button>
                </td>
            </tr>`;
        }).join("")
        : `<tr><td colspan="7" class="empty">No maintenance requests for this filter.</td></tr>`;
}

function renderInvoices() {
    const body = document.querySelector("#invoice-table tbody");
    body.innerHTML = state.invoices.length
        ? state.invoices.map((invoice) => `<tr>
            <td>${esc(invoice.number)}</td>
            <td>${esc(invoice.date)}</td>
            <td>${esc(propertyName(invoice.property_id))}</td>
            <td>${esc(invoice.tenant)}</td>
            <td>${esc(invoice.status)}</td>
            <td class="num">${money(invoice.total)}</td>
            <td class="row-actions">
                <a class="small secondary" href="/invoices/${esc(invoice.id)}" target="_blank" rel="noopener">View</a>
                <a class="small secondary" href="/invoices/${esc(invoice.id)}/pdf">Download PDF</a>
                <a class="small secondary" href="/invoices/${esc(invoice.id)}/xlsx">Export Excel</a>
                <button type="button" class="small secondary" data-action="edit-invoice" data-id="${esc(invoice.id)}">Edit</button>
                <button type="button" class="small danger" data-action="delete-invoice" data-id="${esc(invoice.id)}">Delete</button>
            </td>
        </tr>`).join("")
        : `<tr><td colspan="7" class="empty">No invoices yet.</td></tr>`;
}

function renderTenantOptions() {
    const select = document.getElementById("statement-tenant");
    if (!select) return;
    const current = select.value;
    const names = new Map();
    const add = (value) => {
        const name = String(value || "").trim();
        if (!name) return;
        const key = name.toLocaleLowerCase();
        if (!names.has(key)) names.set(key, name);
    };
    state.income.forEach((row) => add(row.tenant));
    state.invoices.forEach((row) => add(row.tenant));
    const options = ['<option value="">All tenants in this period</option>'];
    [...names.values()].sort((a, b) => a.localeCompare(b)).forEach((name) => {
        options.push(`<option value="${esc(name)}">${esc(name)}</option>`);
    });
    select.innerHTML = options.join("");
    if ([...select.options].some((option) => option.value === current)) {
        select.value = current;
    }
}

function refreshExportLinks() {
    const tenantField = document.getElementById("statement-tenant");
    const tenant = tenantField ? tenantField.value : "";
    document.querySelectorAll("a[data-export]").forEach((link) => {
        const params = new URLSearchParams(query());
        if (link.dataset.tenant === "1" && tenant) params.set("tenant", tenant);
        link.href = link.dataset.export + "?" + params.toString();
    });
}

function render() {
    fillPropertySelects();
    renderSummary();
    renderProperties();
    renderMoney();
    renderMaintenance();
    renderInvoices();
    renderTenantOptions();
    refreshExportLinks();
}

function maintenanceQuery() {
    const params = new URLSearchParams();
    if (state.propertyId) params.set("property_id", state.propertyId);
    if (state.status) params.set("status", state.status);
    return params.toString();
}

async function refresh() {
    const shared = query();
    const invoiceQuery = state.propertyId ? "?property_id=" + encodeURIComponent(state.propertyId) : "";
    const [summary, properties, income, expenses, maintenance, invoices, settings] = await Promise.all([
        api("/api/summary?" + shared),
        api("/api/properties"),
        api("/api/income?" + shared),
        api("/api/expenses?" + shared),
        api("/api/maintenance?" + maintenanceQuery()),
        api("/api/invoices" + invoiceQuery),
        api("/api/settings"),
    ]);
    state.summary = summary;
    state.properties = properties;
    state.income = income;
    state.expenses = expenses;
    state.maintenance = maintenance;
    state.invoices = invoices;
    state.settings = settings;
    applyBranding(settings);
    render();
}

const settingFields = [
    "organisation_name",
    "contact_name",
    "address",
    "phone",
    "email",
    "registration_number",
    "payment_details",
];

function applyBranding(settings) {
    const saved = settings || {};
    const hasLogo = saved.logo ? "1" : "";
    document.querySelectorAll("[data-logo]").forEach((img) => {
        img.dataset.hasLogo = hasLogo;
    });
    showLogo();
    const org = document.getElementById("org-name");
    org.textContent = saved.organisation_name || "";
    org.hidden = !saved.organisation_name;
    const form = document.getElementById("settings-form");
    if (form.contains(document.activeElement)) return;
    settingFields.forEach((key) => {
        if (form.elements[key]) form.elements[key].value = saved[key] || "";
    });
}

function formData(form) {
    return Object.fromEntries(new FormData(form).entries());
}

function resetForm(form, editKey) {
    form.reset();
    state[editKey] = null;
    const date = form.querySelector('input[type="date"]');
    if (date) date.value = today();
    const flag = form.querySelector(".edit-flag");
    if (flag) flag.hidden = true;
    const cancel = form.querySelector("[data-cancel]");
    if (cancel) cancel.hidden = true;
    const submit = form.querySelector('[type="submit"]');
    if (submit && submit.dataset.label) submit.textContent = submit.dataset.label;
    toggleRecovery();
}

function toggleRecovery() {
    const type = document.getElementById("income-type");
    const field = document.getElementById("recovery-field");
    if (!type || !field) return;
    const show = type.value === "Recovery";
    field.hidden = !show;
    const select = document.getElementById("income-recovery");
    if (select) select.required = show;
}

async function saveForm(form, editKey, createUrl, updateUrl, bodyFor) {
    const editing = state[editKey];
    const body = bodyFor(formData(form));
    const url = editing ? updateUrl(editing) : createUrl;
    await api(url, {
        method: editing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    resetForm(form, editKey);
    notice(editing ? "Saved." : "Added.");
    await refresh();
}

function setEditFlag(form, label) {
    const flag = form.querySelector(".edit-flag");
    flag.hidden = false;
    flag.textContent = label;
    const cancel = form.querySelector("[data-cancel]");
    if (cancel) cancel.hidden = false;
    const submit = form.querySelector('[type="submit"]');
    submit.textContent = "Save changes";
}

function showCustomDates() {
    const custom = state.period === "custom";
    document.getElementById("custom-dates").hidden = !custom;
    document.getElementById("custom-end").hidden = !custom;
}

document.getElementById("period").addEventListener("change", async (event) => {
    state.period = event.target.value;
    showCustomDates();
    if (state.period === "custom" && (!state.start || !state.end)) return;
    try {
        await refresh();
    } catch (error) {
        notice(error.message, true);
    }
});

document.getElementById("period-start").addEventListener("change", async (event) => {
    state.start = event.target.value;
    if (state.start && state.end) {
        try { await refresh(); } catch (error) { notice(error.message, true); }
    }
});

document.getElementById("period-end").addEventListener("change", async (event) => {
    state.end = event.target.value;
    if (state.start && state.end) {
        try { await refresh(); } catch (error) { notice(error.message, true); }
    }
});

document.getElementById("property-filter").addEventListener("change", async (event) => {
    state.propertyId = event.target.value;
    try { await refresh(); } catch (error) { notice(error.message, true); }
});

document.getElementById("status-filter").addEventListener("change", async (event) => {
    state.status = event.target.value;
    try { await refresh(); } catch (error) { notice(error.message, true); }
});

document.querySelectorAll(".tabs button[data-tab]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.tab));
});

document.getElementById("property-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
        await saveForm(event.target, "propertyEdit", "/api/properties", (id) => "/api/properties/" + id, (values) => ({
            name: values.name,
            address: values.address,
            kind: values.kind,
            monthly_rent: values.monthly_rent,
            notes: values.notes,
        }));
    } catch (error) {
        notice(error.message, true);
    }
});

document.getElementById("property-cancel").addEventListener("click", () => {
    resetForm(document.getElementById("property-form"), "propertyEdit");
});

document.getElementById("income-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
        await saveForm(event.target, "incomeEdit", "/api/income", (id) => "/api/income/" + id, (values) => ({
            property_id: values.property_id,
            amount: values.amount,
            date: values.date,
            income_type: values.income_type,
            recovery_category: values.income_type === "Recovery" ? values.recovery_category : "",
            tenant: values.tenant,
            description: values.description,
        }));
    } catch (error) {
        notice(error.message, true);
    }
});

document.getElementById("income-type").addEventListener("change", toggleRecovery);

document.getElementById("income-cancel").addEventListener("click", () => {
    resetForm(document.getElementById("income-form"), "incomeEdit");
});

document.getElementById("expense-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = formData(event.target);
    const category = (values.category_custom || "").trim() || values.category;
    try {
        const editing = state.expenseEdit;
        await api(editing ? "/api/expenses/" + editing : "/api/expenses", {
            method: editing ? "PUT" : "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                property_id: values.property_id,
                amount: values.amount,
                date: values.date,
                category,
                vendor: values.vendor,
                description: values.description,
            }),
        });
        resetForm(event.target, "expenseEdit");
        notice(editing ? "Saved." : "Added.");
        await refresh();
    } catch (error) {
        notice(error.message, true);
    }
});

document.getElementById("expense-cancel").addEventListener("click", () => {
    resetForm(document.getElementById("expense-form"), "expenseEdit");
});

document.getElementById("maint-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
        await saveForm(event.target, "maintenanceEdit", "/api/maintenance", (id) => "/api/maintenance/" + id, (values) => ({
            property_id: values.property_id,
            date: values.date,
            issue_type: values.issue_type,
            urgency: values.urgency,
            status: values.status || "Open",
            description: values.description,
            tenant_name: values.tenant_name,
            contact_phone: values.contact_phone,
            cost: values.cost,
            vendor: values.vendor,
            notes: values.notes,
        }));
    } catch (error) {
        notice(error.message, true);
    }
});

document.getElementById("maint-cancel").addEventListener("click", () => {
    resetForm(document.getElementById("maint-form"), "maintenanceEdit");
});

function assign(form, values) {
    Object.entries(values).forEach(([key, value]) => {
        const field = form.elements.namedItem(key);
        if (field) field.value = value == null ? "" : value;
    });
}

document.body.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action]");
    if (!button || button.disabled) return;
    const id = button.dataset.id;
    const action = button.dataset.action;
    try {
        if (action === "edit-property") {
            const prop = state.properties.find((item) => item.id === id);
            const form = document.getElementById("property-form");
            state.propertyEdit = id;
            assign(form, prop);
            setEditFlag(form, "Editing " + prop.name);
            showView("properties");
            return;
        }
        if (action === "focus-property") {
            state.propertyId = id;
            document.getElementById("property-filter").value = id;
            await refresh();
            showView("money");
            return;
        }
        if (action === "delete-property") {
            const prop = state.properties.find((item) => item.id === id);
            const ok = window.confirm(`Delete ${prop.name}? This also removes every income, expense, invoice, and maintenance record linked to it, including records outside the current period.`);
            if (!ok) return;
            await api("/api/properties/" + id, { method: "DELETE" });
            if (state.propertyId === id) state.propertyId = "";
            notice("Property deleted.");
            await refresh();
            return;
        }
        if (action === "edit-income") {
            const entry = state.income.find((item) => item.id === id);
            const form = document.getElementById("income-form");
            state.incomeEdit = id;
            assign(form, entry);
            toggleRecovery();
            setEditFlag(form, "Editing income");
            showView("money");
            return;
        }
        if (action === "edit-expense") {
            const entry = state.expenses.find((item) => item.id === id);
            const form = document.getElementById("expense-form");
            state.expenseEdit = id;
            assign(form, entry);
            const known = [...form.elements.category.options].some((option) => option.value === entry.category);
            form.elements.category.value = known ? entry.category : "Other";
            form.elements.category_custom.value = known ? "" : entry.category;
            setEditFlag(form, "Editing expense");
            showView("money");
            return;
        }
        if (action === "delete-income" || action === "delete-expense") {
            const label = action === "delete-income" ? "income" : "expense";
            if (!window.confirm("Delete this " + label + " record?")) return;
            await api("/api/" + (label === "income" ? "income/" : "expenses/") + id, { method: "DELETE" });
            notice("Deleted.");
            await refresh();
            return;
        }
        if (action === "edit-maintenance") {
            const entry = state.maintenance.find((item) => item.id === id);
            const form = document.getElementById("maint-form");
            state.maintenanceEdit = id;
            assign(form, entry);
            setEditFlag(form, "Editing maintenance request");
            showView("maintenance");
            return;
        }
        if (action === "delete-maintenance") {
            if (!window.confirm("Delete this maintenance request?")) return;
            await api("/api/maintenance/" + id, { method: "DELETE" });
            notice("Deleted.");
            await refresh();
            return;
        }
        if (action === "copy-expense") {
            await api("/api/maintenance/" + id + "/expense", { method: "POST" });
            notice("Copied to expenses as Repairs, using the request date. Open Money and set the period to All time if you do not see it yet.");
            await refresh();
            return;
        }
        if (action === "edit-invoice") {
            const invoice = state.invoices.find((item) => item.id === id);
            const form = document.getElementById("invoice-form");
            state.invoiceEdit = id;
            assign(form, invoice);
            document.getElementById("invoice-lines").innerHTML = "";
            (invoice.line_items || []).forEach((line) => addInvoiceLine(line));
            if (!document.querySelector(".invoice-line")) addInvoiceLine();
            updateInvoiceTotal();
            setEditFlag(form, "Editing " + invoice.number);
            showView("invoices");
            return;
        }
        if (action === "delete-invoice") {
            if (!window.confirm("Delete this invoice?")) return;
            await api("/api/invoices/" + id, { method: "DELETE" });
            if (state.invoiceEdit === id) resetInvoice();
            notice("Deleted.");
            await refresh();
        }
    } catch (error) {
        notice(error.message, true);
    }
});

document.body.addEventListener("change", async (event) => {
    const select = event.target.closest('select[data-action="status"]');
    if (!select) return;
    try {
        await api("/api/maintenance/" + select.dataset.id, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: select.value }),
        });
        notice("Status updated.");
        await refresh();
    } catch (error) {
        notice(error.message, true);
    }
});

function invoiceLines() {
    return [...document.querySelectorAll(".invoice-line")].map((row) => ({
        description: row.querySelector("[data-desc]").value,
        quantity: row.querySelector("[data-qty]").value,
        unit_price: row.querySelector("[data-price]").value,
    })).filter((line) => line.description.trim());
}

function updateInvoiceTotal() {
    const total = [...document.querySelectorAll(".invoice-line")].reduce((sum, row) => {
        const qty = Number(row.querySelector("[data-qty]").value) || 0;
        const price = Number(row.querySelector("[data-price]").value) || 0;
        return sum + qty * price;
    }, 0);
    document.getElementById("invoice-total").textContent = money(total);
}

function addInvoiceLine(line = {}) {
    const row = document.createElement("div");
    row.className = "invoice-line";
    const qty = line.quantity == null || line.quantity === "" ? 1 : line.quantity;
    const price = line.unit_price == null || line.unit_price === "" ? "" : line.unit_price;
    row.innerHTML = `
        <div class="field"><label>Description</label><input data-desc maxlength="200" list="invoice-item-names" value="${esc(line.description || "")}" placeholder="Monthly rent"></div>
        <div class="field"><label>Qty</label><input data-qty type="number" min="0.01" step="0.01" value="${esc(qty)}"></div>
        <div class="field"><label>Unit price (R)</label><input data-price type="number" min="0" step="0.01" value="${esc(price)}"></div>
        <button type="button" class="secondary small" data-remove-line>Remove</button>`;
    document.getElementById("invoice-lines").appendChild(row);
}

function resetInvoice() {
    resetForm(document.getElementById("invoice-form"), "invoiceEdit");
    document.getElementById("invoice-due").value = "";
    document.getElementById("invoice-lines").innerHTML = "";
    addInvoiceLine();
    updateInvoiceTotal();
}

document.getElementById("add-invoice-line").addEventListener("click", () => {
    addInvoiceLine();
    updateInvoiceTotal();
});

document.getElementById("invoice-lines").addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-line]");
    if (!button) return;
    const rows = document.querySelectorAll(".invoice-line");
    if (rows.length === 1) {
        rows[0].querySelector("[data-desc]").value = "";
        rows[0].querySelector("[data-price]").value = "";
        rows[0].querySelector("[data-qty]").value = "1";
    } else {
        button.closest(".invoice-line").remove();
    }
    updateInvoiceTotal();
});

document.getElementById("invoice-lines").addEventListener("input", updateInvoiceTotal);

document.getElementById("invoice-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = formData(event.target);
    const editing = state.invoiceEdit;
    try {
        await api(editing ? "/api/invoices/" + editing : "/api/invoices", {
            method: editing ? "PUT" : "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                property_id: values.property_id,
                tenant: values.tenant,
                date: values.date,
                due_date: values.due_date,
                status: values.status,
                notes: values.notes,
                line_items: invoiceLines(),
            }),
        });
        resetInvoice();
        notice(editing ? "Saved." : "Invoice saved.");
        await refresh();
    } catch (error) {
        notice(error.message, true);
    }
});

document.getElementById("invoice-cancel").addEventListener("click", resetInvoice);

const statementTenant = document.getElementById("statement-tenant");
if (statementTenant) statementTenant.addEventListener("change", refreshExportLinks);

function showLogo() {
    const images = [...document.querySelectorAll("[data-logo]")];
    const enabled = images.some((img) => img.dataset.hasLogo === "1");
    images.forEach((img) => {
        if (!enabled) {
            img.hidden = true;
            img.removeAttribute("src");
            return;
        }
        img.onload = () => { img.hidden = false; };
        img.onerror = () => { img.hidden = true; };
        if (!img.getAttribute("src")) img.src = "/logo?t=" + Date.now();
    });
    const remove = document.getElementById("logo-remove");
    if (remove) remove.hidden = !enabled;
}

document.getElementById("logo-file").addEventListener("change", async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    if (!file) return;
    const body = new FormData();
    body.append("logo", file);
    try {
        await api("/api/logo", { method: "POST", body });
        document.querySelectorAll("[data-logo]").forEach((img) => {
            img.dataset.hasLogo = "1";
            img.removeAttribute("src");
        });
        showLogo();
        notice("Logo updated.");
    } catch (error) {
        notice(error.message, true);
    }
});

document.getElementById("logo-remove").addEventListener("click", async () => {
    try {
        await api("/api/logo", { method: "DELETE" });
        document.querySelectorAll("[data-logo]").forEach((img) => { img.dataset.hasLogo = ""; });
        showLogo();
        notice("Logo removed.");
    } catch (error) {
        notice(error.message, true);
    }
});

document.getElementById("settings-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = formData(event.target);
    const body = {};
    settingFields.forEach((key) => { body[key] = values[key] || ""; });
    try {
        const saved = await api("/api/settings", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        state.settings = saved;
        applyBranding(saved);
        notice("Settings saved.");
    } catch (error) {
        notice(error.message, true);
    }
});

document.querySelectorAll("form input[type='date']").forEach((field) => {
    if (!field.value && field.id !== "invoice-due") field.value = today();
});

toggleRecovery();
resetInvoice();
showLogo();
refresh().catch((error) => notice(error.message, true));
