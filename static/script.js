let threadId = crypto.randomUUID();

const searchForm = document.getElementById("search-form");
const searchInput = document.getElementById("search-input");
const searchError = document.getElementById("search-error");
const searchAutocomplete = document.getElementById("search-autocomplete");

const brandHome = document.getElementById("brand-home");
const hero = document.getElementById("hero");
const heroSearchForm = document.getElementById("hero-search-form");
const heroSearchInput = document.getElementById("hero-search-input");
const heroSearchAutocomplete = document.getElementById(
  "hero-search-autocomplete",
);
const heroChips = document.getElementById("hero-chips");
const dashboard = document.getElementById("dashboard");

const emptyState = document.getElementById("empty-state");
const stockContent = document.getElementById("stock-content");
const stockNameEl = document.getElementById("stock-name");
const stockTickerEl = document.getElementById("stock-ticker");
const stockPriceEl = document.getElementById("stock-price");
const stockChangeEl = document.getElementById("stock-change");
const statHighEl = document.getElementById("stat-high");
const statLowEl = document.getElementById("stat-low");
const stat52wEl = document.getElementById("stat-52w");

const log = document.getElementById("log");
const suggestions = document.getElementById("suggestions");
const chatForm = document.getElementById("composer");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");

let mainChart = null;
let currentCompany = null;
let allTickers = [];

fetch("/tickers")
  .then((r) => r.json())
  .then((data) => {
    allTickers = data.tickers;
  })
  .catch(() => {});

function filterTickers(query) {
  const q = query.trim().toLowerCase();
  if (!q) return [];

  const starts = [];
  const contains = [];
  for (const t of allTickers) {
    const name = t.name.toLowerCase();
    if (name.startsWith(q) || t.code.startsWith(q)) {
      starts.push(t);
    } else if (name.includes(q) || t.code.includes(q)) {
      contains.push(t);
    }
  }
  return [...starts, ...contains].slice(0, 8);
}

function setupAutocomplete(inputEl, listEl) {
  let items = [];
  let activeIndex = 0;

  function render() {
    if (items.length === 0) {
      listEl.hidden = true;
      listEl.innerHTML = "";
      return;
    }
    listEl.innerHTML = items
      .map(
        (t, i) => `
          <div class="autocomplete-item${i === activeIndex ? " active" : ""}" data-index="${i}">
            <span class="autocomplete-name">${t.name}</span>
            <span class="autocomplete-code">${t.code}</span>
          </div>
        `,
      )
      .join("");
    listEl.hidden = false;
  }

  function close() {
    items = [];
    activeIndex = 0;
    listEl.hidden = true;
    listEl.innerHTML = "";
  }

  function select(item) {
    inputEl.value = item.name;
    close();
    performSearch(item.name);
  }

  function refresh() {
    items = filterTickers(inputEl.value);
    activeIndex = 0;
    render();
  }

  inputEl.addEventListener("input", refresh);
  inputEl.addEventListener("focus", refresh);

  inputEl.addEventListener("keydown", (e) => {
    if (listEl.hidden || items.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIndex = (activeIndex + 1) % items.length;
      render();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIndex = (activeIndex - 1 + items.length) % items.length;
      render();
    } else if (e.key === "Enter") {
      e.preventDefault();
      select(items[activeIndex]);
    } else if (e.key === "Escape") {
      close();
    }
  });

  listEl.addEventListener("mousedown", (e) => {
    const row = e.target.closest(".autocomplete-item");
    if (!row) return;
    e.preventDefault();
    select(items[Number(row.dataset.index)]);
  });

  inputEl.addEventListener("blur", () => {
    setTimeout(close, 100);
  });
}

function won(value) {
  return `${Math.round(value).toLocaleString("ko-KR")}원`;
}

function addTurn(text, kind) {
  const turn = document.createElement("div");
  turn.className = `turn turn-${kind}`;

  const bodyEl = document.createElement("div");
  bodyEl.className = "turn-body";
  bodyEl.textContent = text;

  turn.appendChild(bodyEl);
  log.appendChild(turn);
  log.scrollTop = log.scrollHeight;

  return turn;
}

function updateChart(chartData) {
  if (!chartData || chartData.length < 2) return;

  const labels = chartData.map((d) => d.date);
  const closes = chartData.map((d) => d.close);

  if (mainChart) {
    mainChart.data.labels = labels;
    mainChart.data.datasets[0].data = closes;
    mainChart.update();
    return;
  }

  const canvas = document.getElementById("main-chart");
  mainChart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          data: closes,
          borderColor: "#3b82f6",
          backgroundColor: "rgba(59, 130, 246, 0.08)",
          borderWidth: 2,
          pointRadius: 0,
          fill: true,
          tension: 0.2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          ticks: { color: "#9ca3af", maxTicksLimit: 5, font: { size: 11 } },
          grid: { display: false },
        },
        y: {
          ticks: { color: "#9ca3af", font: { size: 11 } },
          grid: { color: "#e8e9ee" },
        },
      },
    },
  });
}

function renderStockPanel(data) {
  emptyState.hidden = true;
  stockContent.hidden = false;
  suggestions.hidden = false;

  stockNameEl.textContent = data.company_name;
  stockTickerEl.textContent = data.ticker.replace(".KS", "");

  const { stats } = data;
  stockPriceEl.textContent = won(stats.current_price);

  const sign = stats.change_pct >= 0 ? "+" : "";
  stockChangeEl.textContent = `${sign}${stats.change_pct}%`;
  stockChangeEl.className = `stock-change ${stats.change_pct >= 0 ? "change-up" : "change-down"}`;

  statHighEl.textContent = won(stats.day_high);
  statLowEl.textContent = won(stats.day_low);
  stat52wEl.textContent = won(stats.year_high);

  updateChart(data.chart);
}

function showDashboard() {
  hero.hidden = true;
  searchForm.hidden = false;
  dashboard.hidden = false;
}

function showHero() {
  dashboard.hidden = true;
  searchForm.hidden = true;
  searchError.hidden = true;
  hero.hidden = false;
  heroSearchInput.value = "";
  heroSearchInput.focus();
}

async function performSearch(companyName) {
  if (!companyName) return;

  searchError.hidden = true;

  const newThreadId = crypto.randomUUID();

  try {
    const res = await fetch("/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        company_name: companyName,
        thread_id: newThreadId,
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `서버 오류 (${res.status})`);
    }

    const data = await res.json();
    threadId = newThreadId;
    currentCompany = data.company_name;
    showDashboard();
    renderStockPanel(data);
    searchInput.value = data.company_name;

    log.innerHTML = "";
    addTurn(
      `${data.company_name}를 불러왔어요. 무엇이 궁금하세요?`,
      "assistant",
    );
  } catch (err) {
    searchError.textContent = err.message;
    searchError.hidden = false;
  }
}

searchForm.addEventListener("submit", (e) => {
  e.preventDefault();
  performSearch(searchInput.value.trim());
});

heroSearchForm.addEventListener("submit", (e) => {
  e.preventDefault();
  performSearch(heroSearchInput.value.trim());
});

heroChips.addEventListener("click", (e) => {
  const chip = e.target.closest(".hero-chip");
  if (!chip) return;
  performSearch(chip.dataset.company);
});

setupAutocomplete(searchInput, searchAutocomplete);
setupAutocomplete(heroSearchInput, heroSearchAutocomplete);

brandHome.addEventListener("click", () => {
  showHero();
});

brandHome.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    showHero();
  }
});

async function sendChat(message) {
  if (!message) return;

  addTurn(message, "user");
  chatInput.value = "";
  chatInput.disabled = true;
  sendBtn.disabled = true;

  const pending = addTurn("조회 중...", "pending assistant");

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, thread_id: threadId }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `서버 오류 (${res.status})`);
    }

    const data = await res.json();
    pending.classList.remove("turn-pending");
    pending.querySelector(".turn-body").textContent = data.response;

    if (data.chart) {
      updateChart(data.chart);
    }
  } catch (err) {
    pending.classList.remove("turn-pending", "turn-assistant");
    pending.classList.add("turn-error");
    pending.querySelector(".turn-body").textContent =
      `요청을 처리하지 못했습니다: ${err.message}`;
  } finally {
    chatInput.disabled = false;
    sendBtn.disabled = false;
    chatInput.focus();
    log.scrollTop = log.scrollHeight;
  }
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  sendChat(chatInput.value.trim());
});

suggestions.addEventListener("click", (e) => {
  const btn = e.target.closest(".pill");
  if (!btn) return;
  sendChat(btn.dataset.question);
});
