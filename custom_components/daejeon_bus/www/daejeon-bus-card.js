/*
 * 대전 버스 카드 (daejeon-bus-card)
 * 대전 버스 통합구성요소가 자동으로 등록한다. 별도 HACS 카드 설치 불필요.
 *
 *   type: custom:daejeon-bus-card
 *   entity: sensor.daejeon_bus_31770            # 정류장 도착정보 요약 센서
 *   # entity: sensor.daejeon_bus_commute_213_31770  # 노선으로 조회 요약 센서
 *   max_rows: 10      # (선택) 보여줄 버스 수
 *   title: 우리집 앞   # (선택) 제목
 */
const CARD_VERSION = "1.0.0";

const ROUTE_TYPE_COLOR = {
  급행: "#e53935",
  간선: "#1e88e5",
  지선: "#43a047",
  외곽: "#8d6e63",
  마을: "#fb8c00",
  첨단: "#8e24aa",
};

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const timeText = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
};

const STYLE = `
  ha-card { overflow: hidden; }
  .header { display: flex; align-items: center; gap: 12px; padding: 14px 16px 10px; }
  .icon { width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
          flex: none; background: var(--dbc-accent-bg); color: var(--dbc-accent); --mdc-icon-size: 22px; }
  .titles { flex: 1; min-width: 0; }
  .title { font-weight: 600; font-size: 15px; color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .subtitle { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  button.refresh { border: none; background: none; cursor: pointer; padding: 8px; border-radius: 50%; color: var(--secondary-text-color);
                   --mdc-icon-size: 22px; display: flex; }
  button.refresh:hover { background: var(--secondary-background-color); }
  button.refresh.busy ha-icon { animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .list { padding: 0 16px 8px; }
  .empty { color: var(--secondary-text-color); padding: 8px 0 14px; font-size: 14px; }
  .row { display: flex; align-items: center; gap: 12px; padding: 10px 0; }
  .row + .row { border-top: 1px solid var(--divider-color, rgba(127,127,127,.2)); }
  .badge { min-width: 52px; text-align: center; padding: 4px 6px; border-radius: 8px; font-weight: 700; font-size: 15px; color: #fff; flex: none; }
  .mid { flex: 1; min-width: 0; }
  .main { font-weight: 600; color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sub { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .right { text-align: right; white-space: nowrap; }
  .eta { font-weight: 700; font-size: 15px; color: var(--primary-text-color); }
  .eta.soon { color: var(--error-color, #db4437); }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 600; color: #fff; }
  .bus { padding: 9px 0; }
  .bus-top { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; font-size: 14px; }
  .bus-top b { color: var(--primary-text-color); }
  .bus-top .km { color: var(--secondary-text-color); }
  .track { position: relative; height: 8px; margin: 8px 0 4px; border-radius: 4px; background: var(--divider-color, rgba(127,127,127,.2)); }
  .fill { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 4px; }
  .track ha-icon { position: absolute; top: -9px; --mdc-icon-size: 22px; }
  .more { font-size: 12px; color: var(--secondary-text-color); padding: 2px 0 6px; }
  .warn { color: var(--error-color, #db4437); padding: 16px; }
  .quota { display: flex; gap: 10px; align-items: flex-start; margin: 0 16px 8px; padding: 10px 12px; border-radius: 8px;
           background: rgba(219, 68, 55, .12); color: var(--error-color, #db4437); font-size: 13px; line-height: 1.4;
           --mdc-icon-size: 20px; }
  .quota b { display: block; }
  .quota span { color: var(--primary-text-color); opacity: .85; }
`;

class DaejeonBusCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("daejeon-bus-card-editor");
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (id) => id.startsWith("sensor.daejeon_bus") && hass.states[id].attributes["버스 목록"] !== undefined
    );
    return { entity: entity || "" };
  }

  setConfig(config) {
    if (!config || !config.entity) throw new Error("entity(대전 버스 요약 센서)를 지정하세요");
    this._config = { max_rows: 10, ...config };
    this._rendered = false;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._config?.entity];
    // 처음 한 번은 꼭 그리고, 그 뒤로는 상태 객체가 바뀔 때만 다시 그림
    if (this._rendered && st === this._lastState && !this._busy) return;
    this._lastState = st;
    this._render();
    this._rendered = true;
  }

  getCardSize() {
    const n = (this._lastState?.attributes?.["버스 목록"] || []).length;
    return 2 + Math.min(n, this._config?.max_rows || 10);
  }

  getGridOptions() {
    return { columns: 6, min_columns: 4, rows: "auto" };
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const st = this._hass?.states[this._config.entity];
    let body;
    if (!this._hass) {
      body = "";
    } else if (!st) {
      body = `<div class="warn">엔티티를 찾을 수 없습니다: ${esc(this._config.entity)}</div>`;
    } else if (st.attributes["버스 목록"] === undefined) {
      body = `<div class="warn">대전 버스 <b>요약 센서</b>를 선택하세요 (예: sensor.daejeon_bus_31770, sensor.daejeon_bus_commute_213_31770)</div>`;
    } else if (st.attributes["내 정류장"] !== undefined) {
      body = this._renderRoute(st);
    } else {
      body = this._renderStation(st);
    }
    if (st && st.attributes["버스 목록"] !== undefined) body = this._quotaBanner(body, st);
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card>${body}</ha-card>`;
    const btn = this.shadowRoot.querySelector("button.refresh");
    if (btn) btn.addEventListener("click", () => this._refresh(st));
  }

  _header(icon, accent, title, subtitle, st) {
    const refresh = st.attributes["새로고침 버튼"];
    return `
      <div class="header" style="--dbc-accent:${accent};--dbc-accent-bg:${accent}22">
        <div class="icon"><ha-icon icon="${icon}"></ha-icon></div>
        <div class="titles">
          <div class="title">${esc(this._config.title || title)}</div>
          <div class="subtitle">${esc(subtitle)}</div>
        </div>
        ${refresh ? `<button class="refresh${this._busy ? " busy" : ""}" title="새로고침"><ha-icon icon="mdi:refresh"></ha-icon></button>` : ""}
      </div>`;
  }

  // 공공데이터포털 일일 요청 한도 초과 안내 (머리글 바로 아래)
  _quotaBanner(body, st) {
    const apis = st.attributes["API 한도 초과"] || [];
    if (!apis.length) return body;
    const t = timeText(st.attributes["마지막 조회"]);
    const banner = `
      <div class="quota"><ha-icon icon="mdi:api-off"></ha-icon><div>
        <b>API 일일 호출 한도 초과</b>
        <span>${esc(apis.join(", "))} · 매일 0시에 초기화됩니다.${t ? ` 아래는 ${esc(t)} 기준 정보입니다.` : ""}</span>
      </div></div>`;
    const cut = body.indexOf('<div class="list">');
    return cut < 0 ? body + banner : body.slice(0, cut) + banner + body.slice(cut);
  }

  async _refresh(st) {
    const entity_id = st?.attributes["새로고침 버튼"];
    if (!entity_id || this._busy) return;
    this._busy = true;
    this._render();
    try {
      await this._hass.callService("button", "press", { entity_id });
    } finally {
      this._busy = false;
      this._render();
    }
  }

  _updated(st) {
    const t = timeText(st.attributes["마지막 조회"]);
    return t ? ` · ${t} 조회` : "";
  }

  // ---- 정류장 도착정보 ----
  _renderStation(st) {
    const a = st.attributes;
    const buses = a["버스 목록"] || [];
    const name = a["정류소 이름"] || "정류장";
    const header = this._header(
      "mdi:bus-stop",
      "#2196f3",
      `${name} (${a["정류소 ID(arsId)"] ?? ""})`,
      `도착예정 ${st.state}대${this._updated(st)}`,
      st
    );
    if (!buses.length) return header + `<div class="list"><div class="empty">도착 예정인 버스가 없습니다</div></div>`;

    const pill = (text, bg) => `<span class="pill" style="background:${bg}">${esc(text)}</span>`;
    const rows = buses.slice(0, this._config.max_rows).map((b) => {
      const status = b["운행 상태"];
      let right;
      if (status === "진입중" || status === "도착") {
        right = pill(status, "var(--error-color, #db4437)");
      } else if (status === "운행대기") {
        right = pill("운행대기", "var(--disabled-text-color, #9e9e9e)");
      } else {
        const soon = status === "곧 도착";
        const stops = b["잔여 정류장 수"];
        const sub = [stops != null ? `${stops}정류장 전` : "", soon && b["도착예정시간"] ? b["도착예정시간"] : ""]
          .filter(Boolean).join(" · ");
        right = `<div class="eta${soon ? " soon" : ""}">${esc(soon ? "곧 도착" : b["도착예정시간"] || "-")}</div>
                 <div class="sub">${esc(sub)}</div>`;
      }
      const lastCat = b["첫/막차"];
      const tag = lastCat === "첫차" || lastCat === "막차" ? " " + pill(lastCat, "#455a64") : "";
      const last = b["최근 통과 정류소"] ? `${b["최근 통과 정류소"]} 통과` : status === "운행대기" ? "차고지 대기" : "-";
      const dest = b["행선지"] ? `${b["행선지"]} 방면` : "";
      const color = ROUTE_TYPE_COLOR[b["노선유형"]] || "var(--primary-color)";
      return `
        <div class="row">
          <div class="badge" style="background:${color}">${esc(b["노선"])}</div>
          <div class="mid"><div class="main">${esc(last)}${tag}</div><div class="sub">${esc(dest)}</div></div>
          <div class="right">${right}</div>
        </div>`;
    });
    const more = buses.length > this._config.max_rows ? `<div class="more">외 ${buses.length - this._config.max_rows}개 노선</div>` : "";
    return header + `<div class="list">${rows.join("")}${more}</div>`;
  }

  // ---- 노선으로 조회 ----
  _renderRoute(st) {
    const a = st.attributes;
    const buses = a["버스 목록"] || [];
    const first = buses[0];
    let subtitle = "오는 버스 없음";
    let accent = "#9e9e9e";
    if (first) {
      const n = first["남은 정류장"];
      subtitle = `첫 번째 버스 ${n}정류장 전${first["도착예정시간"] ? " · " + first["도착예정시간"] : ""}`;
      accent = n <= 3 ? "#f44336" : n <= 7 ? "#ff9800" : "#2196f3";
    }
    const header = this._header("mdi:bus-clock", accent, `${a["노선번호"]}번 → ${a["내 정류장"] || ""}`, subtitle + this._updated(st), st);
    if (!buses.length) return header + `<div class="list"><div class="empty">오고 있는 버스가 없습니다</div></div>`;

    const scale = this._config.scale_stops || 30;
    const rows = buses.slice(0, this._config.max_rows).map((b, i) => {
      const stops = b["남은 정류장"];
      const km = (b["남은 거리(m)"] / 1000).toFixed(1);
      // 가까울수록 막대가 길어짐 (내 정류장 = 오른쪽 끝)
      const pct = Math.max(6, Math.round(100 - (Math.min(stops, scale) / scale) * 100));
      const color = i === 0 ? (stops <= 3 ? "var(--error-color, #db4437)" : "var(--primary-color)") : "var(--secondary-text-color)";
      const eta = b["도착예정시간"] ? `<span style="font-weight:600;color:${color}">${esc(b["도착예정시간"])}</span>` : "";
      return `
        <div class="bus">
          <div class="bus-top"><span><b>${i + 1}번째 · ${esc(stops)}정류장 전</b> <span class="km">(${km}km)</span></span>${eta}</div>
          <div class="track">
            <div class="fill" style="width:${pct}%;background:${color};opacity:${i === 0 ? 1 : 0.55}"></div>
            <ha-icon icon="mdi:bus-side" style="left:calc(${pct}% - 13px);color:${color}"></ha-icon>
          </div>
          <div class="sub">현재 ${esc(b["현재 정류장"])} · ${esc(b["차량번호"])}</div>
        </div>`;
    });
    const more = buses.length > this._config.max_rows ? `<div class="more">외 ${buses.length - this._config.max_rows}대</div>` : "";
    return header + `<div class="list">${rows.join("")}${more}</div>`;
  }
}

// ---- 카드 편집기 (UI) ----
const EDITOR_SCHEMA = [
  { name: "entity", required: true, selector: { entity: { filter: { integration: "daejeon_bus", domain: "sensor" } } } },
  { name: "title", selector: { text: {} } },
  { name: "max_rows", selector: { number: { min: 1, max: 30, mode: "box" } } },
];
const EDITOR_LABELS = {
  entity: "요약 센서 (sensor.daejeon_bus_<정류장> 또는 sensor.daejeon_bus_commute_<노선>_<정류장>)",
  title: "제목 (비우면 자동)",
  max_rows: "보여줄 버스 수",
};

class DaejeonBusCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schema) => EDITOR_LABELS[schema.name] || schema.name;
      this._form.addEventListener("value-changed", (ev) => {
        this._config = ev.detail.value;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = EDITOR_SCHEMA;
    this._form.data = this._config;
  }
}

if (!customElements.get("daejeon-bus-card")) customElements.define("daejeon-bus-card", DaejeonBusCard);
if (!customElements.get("daejeon-bus-card-editor")) customElements.define("daejeon-bus-card-editor", DaejeonBusCardEditor);

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "daejeon-bus-card")) {
  window.customCards.push({
    type: "daejeon-bus-card",
    name: "대전 버스",
    description: "대전 버스 정류장 도착정보 / 노선으로 조회 카드",
    preview: true,
    documentationURL: "https://github.com/phoenix9469/DaejeonBus_HA",
  });
}
console.info(`%c DAEJEON-BUS-CARD %c ${CARD_VERSION} `, "background:#1e88e5;color:#fff", "background:#eee;color:#333");
