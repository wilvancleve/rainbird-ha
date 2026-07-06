/*
 * Rain Bird (self-hosted IQ4) — zone visualization card.
 *
 * Original custom Lovelace card for the `rainbird_ha` integration. Zero-config:
 * it auto-discovers a controller's zone switches, per-zone run-time numbers, and
 * status entities. Optional config:
 *
 *   type: custom:rainbird-ha-card
 *   title: Irrigation        # optional header title
 *   prefix: vanlock_esp_me3   # optional; pin to one controller's entity prefix
 *
 * Builds its DOM once and updates values in place (no full re-render), so it stays
 * smooth and never steals focus.
 */

const STATE_ON = "on";

class RainbirdHaCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._built = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    if (this._built) this._update();
  }

  getCardSize() {
    return 2 + Math.ceil((this._zones ? this._zones.length : 4) / 2);
  }

  connectedCallback() {
    if (!this._timer) this._timer = setInterval(() => this._tick(), 1000);
  }

  disconnectedCallback() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
    this._hideConfirm();
  }

  // ---- discovery ----
  _discover() {
    const hass = this._hass;
    const pin = this._config.prefix;
    const switches = {};
    const runtimes = {};
    for (const eid of Object.keys(hass.states)) {
      let m = eid.match(/^switch\.(.+)_station_(\d+)$/);
      if (m) {
        if (pin && m[1] !== pin) continue;
        (switches[m[1]] = switches[m[1]] || {})[parseInt(m[2], 10)] = eid;
        continue;
      }
      m = eid.match(/^number\.(.+)_station_(\d+)_run_time$/);
      if (m) {
        if (pin && m[1] !== pin) continue;
        (runtimes[m[1]] = runtimes[m[1]] || {})[parseInt(m[2], 10)] = eid;
      }
    }
    const prefix = pin || Object.keys(switches).sort()[0];
    this._prefix = prefix;
    this._zones = [];
    if (!prefix) return;
    const nums = Object.keys(switches[prefix] || {}).map(Number).sort((a, b) => a - b);
    for (const n of nums) {
      this._zones.push({
        num: n,
        sw: switches[prefix][n],
        rt: (runtimes[prefix] || {})[n] || null,
      });
    }
    // Moisture sensor id may carry an area prefix (e.g. binary_sensor.outside_<prefix>_moisture_sensor),
    // so match by prefix + "moisture" rather than an exact id.
    const moisture = Object.keys(this._hass.states).find(
      (e) => e.startsWith("binary_sensor.") && e.includes(prefix) && e.includes("moisture"),
    );
    this._status = {
      conn: `binary_sensor.${prefix}_connectivity`,
      active: `sensor.${prefix}_active_zone`,
      remain: `sensor.${prefix}_time_remaining`,
      rain: `number.${prefix}_rain_delay`,
      power: `switch.${prefix}_controller`,
      moisture: moisture || null,
    };
    this._programs = Object.keys(this._hass.states)
      .filter((e) => e.startsWith(`sensor.${prefix}_program_`))
      .sort();
  }

  _name(eid) {
    const s = this._hass.states[eid];
    let n = (s && s.attributes && s.attributes.friendly_name) || eid;
    // Trim the controller prefix from the friendly name for a compact label.
    const parts = n.split(" ");
    if (parts.length > 2) n = parts.slice(-2).join(" "); // e.g. "Station 001"
    return n;
  }

  _num(eid, fallback) {
    const s = this._hass.states[eid];
    if (!s || s.state === "unknown" || s.state === "unavailable") return fallback;
    const v = Number(s.state);
    return Number.isFinite(v) ? v : fallback;
  }

  _call(domain, service, data) {
    this._hass.callService(domain, service, data);
  }

  _setNumber(eid, value) {
    if (!eid) return;
    const s = this._hass.states[eid];
    const min = (s && s.attributes.min) ?? 1;
    const max = (s && s.attributes.max) ?? 240;
    const v = Math.max(min, Math.min(max, value));
    this._call("number", "set_value", { entity_id: eid, value: v });
  }

  // ---- build DOM once ----
  _build() {
    if (!this._hass) return;
    this._discover();
    if (!this._prefix) {
      this.innerHTML =
        `<ha-card><div style="padding:16px;color:var(--secondary-text-color)">` +
        `No Rain Bird (self-hosted IQ4) zones found.</div></ha-card>`;
      return;
    }

    const card = document.createElement("ha-card");
    card.innerHTML = `
      <style>
        .rb-head{display:flex;align-items:center;gap:12px;padding:16px 16px 8px}
        .rb-icon{--mdc-icon-size:28px;color:var(--primary-color)}
        .rb-power{margin-left:auto;cursor:pointer;border:none;background:none;padding:4px;
          border-radius:50%;color:var(--primary-color);display:inline-flex;line-height:0;
          transition:color .2s,background .2s}
        .rb-power ha-icon{--mdc-icon-size:26px;pointer-events:none}
        .rb-power:hover{background:var(--secondary-background-color)}
        .rb-power.off{color:var(--disabled-color)}
        .rb-modal{position:fixed;inset:0;z-index:99999;display:flex;align-items:center;
          justify-content:center;background:rgba(0,0,0,.5)}
        .rb-modal-box{background:var(--ha-card-background,var(--card-background-color,#fff));
          color:var(--primary-text-color);border-radius:16px;padding:20px;max-width:330px;
          width:calc(100% - 48px);box-shadow:0 10px 45px rgba(0,0,0,.45)}
        .rb-modal-title{display:flex;align-items:center;gap:8px;font-size:1.1rem;font-weight:700;margin-bottom:8px}
        .rb-modal-msg{font-size:.86rem;color:var(--secondary-text-color);line-height:1.45;margin-bottom:18px}
        .rb-modal-actions{display:flex;justify-content:flex-end;gap:8px}
        .rb-modal-actions button{cursor:pointer;border:none;border-radius:10px;padding:9px 16px;
          font-size:.85rem;font-weight:600}
        .rb-modal-cancel{background:var(--secondary-background-color);color:var(--primary-text-color)}
        .rb-modal-confirm{background:var(--error-color,#e53935);color:#fff}
        .rb-title{font-size:1.15rem;font-weight:600;line-height:1.1}
        .rb-sub{font-size:.8rem;color:var(--secondary-text-color)}
        .rb-pills{display:flex;flex-wrap:wrap;gap:6px;padding:0 16px 10px}
        .rb-pill{display:inline-flex;align-items:center;gap:5px;font-size:.72rem;
          padding:3px 9px;border-radius:999px;background:var(--secondary-background-color);
          color:var(--secondary-text-color)}
        .rb-dot{width:8px;height:8px;border-radius:50%;background:var(--disabled-color)}
        .rb-dot.ok{background:var(--success-color,#43a047)}
        .rb-dot.bad{background:var(--error-color,#e53935)}
        .rb-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
          gap:10px;padding:4px 16px 16px}
        .rb-zone{position:relative;overflow:hidden;border-radius:14px;padding:12px;
          background:var(--secondary-background-color);
          border:1px solid var(--divider-color);transition:border-color .2s}
        .rb-zone.run{border-color:var(--success-color,#43a047)}
        .rb-bar{position:absolute;left:0;bottom:0;height:3px;width:0;
          background:var(--success-color,#43a047);transition:width 1s linear}
        .rb-ztop{display:flex;align-items:center;gap:8px}
        .rb-badge{flex:0 0 auto;width:28px;height:28px;border-radius:50%;
          display:flex;align-items:center;justify-content:center;font-size:.78rem;
          font-weight:600;background:var(--card-background-color);
          border:1px solid var(--divider-color);color:var(--primary-text-color)}
        .rb-zone.run .rb-badge{background:var(--success-color,#43a047);color:#fff;border-color:transparent}
        .rb-zname{font-size:.9rem;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .rb-zstat{font-size:.74rem;color:var(--secondary-text-color);margin:8px 0 10px;min-height:1em}
        .rb-zstat.run{color:var(--success-color,#2e7d32)}
        .rb-row{display:flex;align-items:center;justify-content:space-between;gap:8px}
        .rb-dur{display:inline-flex;align-items:center;gap:2px;font-size:.78rem;color:var(--secondary-text-color)}
        .rb-step{cursor:pointer;--mdc-icon-size:18px;color:var(--secondary-text-color);border-radius:50%}
        .rb-step:hover{color:var(--primary-color)}
        .rb-durval{min-width:34px;text-align:center;color:var(--primary-text-color)}
        .rb-btn{cursor:pointer;border:none;border-radius:10px;padding:6px 12px;font-size:.78rem;
          font-weight:600;color:#fff;background:var(--success-color,#43a047)}
        .rb-btn.stop{background:var(--error-color,#e53935)}
        .rb-foot{display:flex;align-items:center;justify-content:space-between;
          gap:10px;padding:0 16px 14px}
        .rb-rain{display:inline-flex;align-items:center;gap:4px;font-size:.8rem;color:var(--secondary-text-color)}
        .rb-stopall{cursor:pointer;font-size:.74rem;color:var(--error-color,#e53935);
          background:none;border:1px solid var(--error-color,#e53935);border-radius:999px;padding:3px 10px}
        .rb-stopall[hidden]{display:none}
        .rb-sched{padding:2px 16px 14px}
        .rb-sched-h{font-size:.72rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
          color:var(--secondary-text-color);margin:2px 0 6px}
        .rb-prow{display:flex;align-items:flex-start;gap:10px;padding:8px 0;cursor:pointer;
          border-top:1px solid var(--divider-color)}
        .rb-pbadge{flex:0 0 auto;width:24px;height:24px;border-radius:6px;display:flex;
          align-items:center;justify-content:center;font-size:.72rem;font-weight:700;
          background:var(--card-background-color);border:1px solid var(--divider-color)}
        .rb-prow.on .rb-pbadge{background:var(--primary-color);color:#fff;border-color:transparent}
        .rb-pmain{flex:1;min-width:0}
        .rb-pdays{font-size:.84rem}
        .rb-pdays.off{color:var(--disabled-color)}
        .rb-pchips{margin-top:5px;display:flex;flex-wrap:wrap;gap:4px}
        .rb-chip{font-size:.68rem;padding:2px 7px;border-radius:6px;
          background:var(--secondary-background-color);color:var(--secondary-text-color)}
      </style>
      <div class="rb-head">
        <ha-icon class="rb-icon" icon="mdi:sprinkler-variant"></ha-icon>
        <div>
          <div class="rb-title"></div>
          <div class="rb-sub"></div>
        </div>
        <button class="rb-power"><ha-icon icon="mdi:power"></ha-icon></button>
      </div>
      <div class="rb-pills">
        <span class="rb-pill rb-p-conn"><span class="rb-dot"></span><span class="rb-conn-txt"></span></span>
        <span class="rb-pill rb-p-run"></span>
        <span class="rb-pill rb-p-moist" hidden></span>
        <span class="rb-pill rb-p-rain"></span>
      </div>
      <div class="rb-grid"></div>
      <div class="rb-sched"></div>
      <div class="rb-foot">
        <span class="rb-rain">
          <ha-icon icon="mdi:weather-rainy" style="--mdc-icon-size:18px"></ha-icon>
          Rain delay
          <ha-icon class="rb-step rb-rain-dn" icon="mdi:minus-circle-outline"></ha-icon>
          <span class="rb-durval rb-rain-val"></span>d
          <ha-icon class="rb-step rb-rain-up" icon="mdi:plus-circle-outline"></ha-icon>
        </span>
        <button class="rb-stopall">Stop all</button>
      </div>
    `;

    this._els = {
      title: card.querySelector(".rb-title"),
      sub: card.querySelector(".rb-sub"),
      connDot: card.querySelector(".rb-p-conn .rb-dot"),
      connTxt: card.querySelector(".rb-conn-txt"),
      pillRun: card.querySelector(".rb-p-run"),
      pillMoist: card.querySelector(".rb-p-moist"),
      pillRain: card.querySelector(".rb-p-rain"),
      grid: card.querySelector(".rb-grid"),
      rainVal: card.querySelector(".rb-rain-val"),
      stopAll: card.querySelector(".rb-stopall"),
      power: card.querySelector(".rb-power"),
      zones: [],
    };

    // Confirmation modal for turning the whole controller OFF (turning it back
    // on is harmless, so that's a direct tap).
    const modal = document.createElement("div");
    modal.className = "rb-modal";
    modal.innerHTML = `
      <div class="rb-modal-box">
        <div class="rb-modal-title">
          <ha-icon icon="mdi:power" style="--mdc-icon-size:22px"></ha-icon>
          Turn controller off?
        </div>
        <div class="rb-modal-msg">This stops any watering in progress and prevents
          scheduled programs from running until you turn the controller back on.</div>
        <div class="rb-modal-actions">
          <button class="rb-modal-cancel">Cancel</button>
          <button class="rb-modal-confirm">Turn off</button>
        </div>
      </div>`;
    modal.addEventListener("click", (e) => {
      if (e.target === modal) this._hideConfirm();
    });
    modal.querySelector(".rb-modal-cancel")
      .addEventListener("click", () => this._hideConfirm());
    modal.querySelector(".rb-modal-confirm").addEventListener("click", () => {
      this._call("switch", "turn_off", { entity_id: this._status.power });
      this._hideConfirm();
    });
    this._modal = modal;

    this._els.power.addEventListener("click", () => {
      const on = (this._hass.states[this._status.power] || {}).state === STATE_ON;
      if (on) this._showConfirm();
      else this._call("switch", "turn_on", { entity_id: this._status.power });
    });

    this._els.title.textContent = this._config.title || "Irrigation";

    // Rain delay steppers
    card.querySelector(".rb-rain-dn").addEventListener("click", () =>
      this._setNumber(this._status.rain, this._num(this._status.rain, 0) - 1));
    card.querySelector(".rb-rain-up").addEventListener("click", () =>
      this._setNumber(this._status.rain, this._num(this._status.rain, 0) + 1));
    this._els.stopAll.addEventListener("click", () => {
      for (const z of this._zones) {
        if ((this._hass.states[z.sw] || {}).state === STATE_ON)
          this._call("switch", "turn_off", { entity_id: z.sw });
      }
    });

    for (const z of this._zones) {
      const tile = document.createElement("div");
      tile.className = "rb-zone";
      tile.innerHTML = `
        <div class="rb-bar"></div>
        <div class="rb-ztop">
          <div class="rb-badge">${z.num}</div>
          <div class="rb-zname"></div>
        </div>
        <div class="rb-zstat"></div>
        <div class="rb-row">
          <span class="rb-dur">
            <ha-icon class="rb-step rb-dn" icon="mdi:minus-circle-outline"></ha-icon>
            <span class="rb-durval"></span><span style="font-size:.7rem">m</span>
            <ha-icon class="rb-step rb-up" icon="mdi:plus-circle-outline"></ha-icon>
          </span>
          <button class="rb-btn">Run</button>
        </div>`;
      const refs = {
        tile,
        bar: tile.querySelector(".rb-bar"),
        name: tile.querySelector(".rb-zname"),
        stat: tile.querySelector(".rb-zstat"),
        durVal: tile.querySelector(".rb-durval"),
        btn: tile.querySelector(".rb-btn"),
      };
      tile.querySelector(".rb-dn").addEventListener("click", () =>
        this._setNumber(z.rt, this._num(z.rt, 10) - 1));
      tile.querySelector(".rb-up").addEventListener("click", () =>
        this._setNumber(z.rt, this._num(z.rt, 10) + 1));
      refs.btn.addEventListener("click", () => {
        const on = (this._hass.states[z.sw] || {}).state === STATE_ON;
        this._call("switch", on ? "turn_off" : "turn_on", { entity_id: z.sw });
      });
      refs.name.addEventListener("click", () =>
        this._moreInfo(z.sw));
      this._els.grid.appendChild(tile);
      this._els.zones.push({ z, refs });
    }

    // Schedule panel (display only) — one row per program sensor.
    const sched = card.querySelector(".rb-sched");
    this._els.programs = [];
    if (this._programs.length) {
      sched.innerHTML = `<div class="rb-sched-h">Schedule</div>`;
      for (const eid of this._programs) {
        const short = eid.split("_program_").pop().toUpperCase();
        const row = document.createElement("div");
        row.className = "rb-prow";
        row.innerHTML =
          `<div class="rb-pbadge">${short}</div>` +
          `<div class="rb-pmain"><div class="rb-pdays"></div>` +
          `<div class="rb-pchips"></div></div>`;
        row.addEventListener("click", () => this._moreInfo(eid));
        sched.appendChild(row);
        this._els.programs.push({
          eid, row,
          days: row.querySelector(".rb-pdays"),
          chips: row.querySelector(".rb-pchips"),
        });
      }
    }

    this.innerHTML = "";
    this.appendChild(card);
    this._built = true;
  }

  _moreInfo(eid) {
    this.dispatchEvent(new CustomEvent("hass-more-info", {
      detail: { entityId: eid }, bubbles: true, composed: true,
    }));
  }

  _showConfirm() {
    // Append inside the card (not document.body) so the card's scoped styles
    // reach it; position:fixed still overlays the viewport.
    if (this._modal && !this._modal.parentNode) this.appendChild(this._modal);
  }

  _hideConfirm() {
    if (this._modal && this._modal.parentNode) this._modal.remove();
  }

  _fmt(sec) {
    sec = Math.max(0, Math.round(sec));
    const m = Math.floor(sec / 60), s = sec % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  // Best estimate of the running zone's TOTAL seconds, so the bar shows a true
  // proportion even when we join mid-run. Candidates are the zone's configured
  // durations: its manual run-time, and any program step for that zone (adjusted
  // by the program's seasonal %). Pick the smallest candidate the current
  // remaining still fits under; fall back to the remaining itself.
  _runTotal(z, firstRemaining) {
    const cands = [];
    const rt = z.rt ? this._num(z.rt, 0) * 60 : 0;
    if (rt) cands.push(rt);
    for (const eid of this._programs || []) {
      const a = (this._hass.states[eid] || {}).attributes || {};
      const pct = (a.seasonal_adjust_pct == null ? 100 : a.seasonal_adjust_pct) / 100;
      for (const s of a.stations || []) {
        if (s.terminal === z.num && s.minutes > 0) {
          cands.push(Math.round(s.minutes * pct * 60));
        }
      }
    }
    const fits = cands.filter((c) => c >= firstRemaining - 2).sort((a, b) => a - b);
    return fits.length ? fits[0] : Math.max(firstRemaining, 1);
  }

  // Repaint the running zone's bar + "time left" from the anchor. Called both
  // on hass updates and every second by the ticker, so it animates smoothly.
  _paintTime() {
    if (!this._run) return;
    const remaining = Math.max(0, this._run.finish - Date.now() / 1000);
    const ez = this._els.zones.find((e) => e.z.num === this._run.num);
    if (ez) {
      const total = this._run.total || 1;
      ez.refs.bar.style.width =
        Math.max(0, Math.min(100, (remaining / total) * 100)) + "%";
      ez.refs.stat.textContent = `Running · ${this._fmt(remaining)} left`;
    }
    this._els.sub.textContent =
      `Zone ${this._run.num} watering · ${this._fmt(remaining)} left`;
  }

  _tick() {
    if (this._built && this._run) this._paintTime();
  }

  // ---- update values in place ----
  _update() {
    if (!this._built) return;
    const hass = this._hass;
    const remain = this._num(this._status.remain, 0);
    let running = 0;
    let runZone = null;

    for (const { z, refs } of this._els.zones) {
      const on = (hass.states[z.sw] || {}).state === STATE_ON;
      refs.name.textContent = this._name(z.sw);
      refs.durVal.textContent = z.rt ? this._num(z.rt, 10) : "—";
      refs.tile.classList.toggle("run", !!on);
      refs.stat.classList.toggle("run", !!on);
      refs.btn.textContent = on ? "Stop" : "Run";
      refs.btn.classList.toggle("stop", !!on);
      if (on) {
        running++;
        runZone = { z, refs };
      } else {
        refs.bar.style.width = "0";
        refs.stat.textContent = "Idle";
      }
    }

    // Anchor the running zone's countdown to when the remaining-sensor last
    // changed, so the 1s ticker can interpolate accurately between updates and
    // re-sync whenever a fresh value arrives.
    if (runZone) {
      const rem = hass.states[this._status.remain];
      const t0 = rem && rem.last_changed
        ? Date.parse(rem.last_changed) / 1000 : Date.now() / 1000;
      const finish = t0 + remain;
      if (!this._run || this._run.num !== runZone.z.num) {
        this._run = {
          num: runZone.z.num, finish,
          total: this._runTotal(runZone.z, remain),
        };
      } else {
        this._run.finish = finish;
        this._run.total = Math.max(this._run.total, remain);
      }
    } else {
      this._run = null;
    }

    // Header + pills
    const connOn = (hass.states[this._status.conn] || {}).state === STATE_ON;
    this._els.connDot.className = "rb-dot " + (connOn ? "ok" : "bad");
    this._els.connTxt.textContent = connOn ? "Online" : "Offline";

    const powerOn = (hass.states[this._status.power] || {}).state === STATE_ON;
    this._els.power.classList.toggle("off", !powerOn);
    this._els.power.title = powerOn
      ? "Controller On — tap to turn off"
      : "Controller Off — tap to turn on";
    this._els.pillRun.textContent = running
      ? `${running} running`
      : `${this._zones.length} zones idle`;
    const moist = this._status.moisture && hass.states[this._status.moisture];
    if (moist && moist.state !== "unavailable") {
      this._els.pillMoist.hidden = false;
      this._els.pillMoist.textContent =
        moist.state === "on" ? "Moisture: wet" : "Moisture: dry";
    } else {
      this._els.pillMoist.hidden = true;
    }
    const rain = this._num(this._status.rain, 0);
    this._els.pillRain.textContent = rain > 0 ? `Rain delay ${rain}d` : "No rain delay";
    this._els.rainVal.textContent = rain;
    this._els.stopAll.hidden = running === 0;
    if (!running) {
      this._els.sub.textContent = connOn ? "All zones idle" : "Controller offline";
    }
    this._paintTime();  // fill the running zone's live time immediately

    // Schedule rows
    for (const p of (this._els.programs || [])) {
      const s = hass.states[p.eid];
      const a = (s && s.attributes) || {};
      const runs = !!(s && s.state && s.state !== "Off" && s.state !== "Unknown"
                      && s.state !== "unavailable");
      p.row.classList.toggle("on", runs);
      p.days.classList.toggle("off", !runs);
      p.days.textContent = runs ? s.state : "Off";
      const chips = (a.stations || [])
        .filter((x) => x.minutes > 0)
        .map((x) => `<span class="rb-chip">${x.terminal} · ${x.minutes}m</span>`);
      p.chips.innerHTML = runs ? chips.join("") : "";
    }
  }
}

customElements.define("rainbird-ha-card", RainbirdHaCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "rainbird-ha-card",
  name: "Rain Bird (self-hosted IQ4) Zones",
  description: "Zone visualization for the rainbird_ha integration.",
});
