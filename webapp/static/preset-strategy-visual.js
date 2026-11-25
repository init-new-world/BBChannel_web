const COLOR_ORDER = ["B", "A", "Q"];
const COLOR_META = {
  B: { labelKey: "Buster", short: "红", cls: "card-buster" },
  A: { labelKey: "Arts", short: "蓝", cls: "card-arts" },
  Q: { labelKey: "Quick", short: "绿", cls: "card-quick" },
};

export function buildMainAttackerOrder(mainSlot = 1, primaryColor = "B") {
  const slot = [1, 2, 3].includes(mainSlot) ? mainSlot : 1;
  const otherSlots = [1, 2, 3].filter((s) => s !== slot);
  const colors = [primaryColor, ...COLOR_ORDER.filter((c) => c !== primaryColor)];
  const result = colors.map((c) => `${slot}${c}`);
  for (const c of COLOR_ORDER) {
    for (const s of otherSlots) {
      result.push(`${s}${c}`);
    }
  }
  return result;
}

export function buildAllCardsByColorOrder(primaryColor = "B") {
  const colors = [primaryColor, ...COLOR_ORDER.filter((c) => c !== primaryColor)];
  const result = [];
  for (const c of colors) {
    for (const s of [1, 2, 3]) {
      result.push(`${s}${c}`);
    }
  }
  return result;
}

export const STRATEGY_QUICK_TEMPLATES = [
  {
    id: "np-buster",
    labelKey: "1 NP + Buster Follow-up",
    build(mainSlot = 1) {
      const follow = buildMainAttackerOrder(mainSlot, "B");
      return {
        card1: { type: 0, cards: [mainSlot], criticalStar: 0, more_or_less: true },
        card2: { type: 1, cards: [...follow], criticalStar: 0, more_or_less: true },
        card3: { type: 1, cards: [...follow], criticalStar: 0, more_or_less: true },
        breakpoint: [false, false],
        colorFirst: true,
      };
    },
  },
  {
    id: "np-arts",
    labelKey: "1 NP + Arts Follow-up",
    build(mainSlot = 1) {
      const follow = buildMainAttackerOrder(mainSlot, "A");
      return {
        card1: { type: 0, cards: [mainSlot], criticalStar: 0, more_or_less: true },
        card2: { type: 1, cards: [...follow], criticalStar: 0, more_or_less: true },
        card3: { type: 1, cards: [...follow], criticalStar: 0, more_or_less: true },
        breakpoint: [false, false],
        colorFirst: true,
      };
    },
  },
  {
    id: "np-quick",
    labelKey: "1 NP + Quick Follow-up",
    build(mainSlot = 1) {
      const follow = buildMainAttackerOrder(mainSlot, "Q");
      return {
        card1: { type: 0, cards: [mainSlot], criticalStar: 0, more_or_less: true },
        card2: { type: 1, cards: [...follow], criticalStar: 0, more_or_less: true },
        card3: { type: 1, cards: [...follow], criticalStar: 0, more_or_less: true },
        breakpoint: [false, false],
        colorFirst: true,
      };
    },
  },
  {
    id: "np-no-chain",
    labelKey: "1 NP + Avoid Same-Servant Chain",
    build(mainSlot = 1) {
      return {
        card1: { type: 0, cards: [mainSlot], criticalStar: 0, more_or_less: true },
        card2: { type: 2, cards: [], criticalStar: 0, more_or_less: true },
        card3: { type: 2, cards: [], criticalStar: 0, more_or_less: true },
        breakpoint: [false, true],
        colorFirst: true,
      };
    },
  },
  {
    id: "face-buster",
    labelKey: "3 Face Cards · Buster First",
    build() {
      const order = buildAllCardsByColorOrder("B");
      return {
        card1: { type: 1, cards: [...order], criticalStar: 0, more_or_less: true },
        card2: { type: 1, cards: [...order], criticalStar: 0, more_or_less: true },
        card3: { type: 1, cards: [...order], criticalStar: 0, more_or_less: true },
        breakpoint: [true, true],
        colorFirst: true,
      };
    },
  },
  {
    id: "face-crit",
    labelKey: "3 Face Cards · High Crit First",
    build(mainSlot = 1) {
      const order = buildMainAttackerOrder(mainSlot, "B");
      return {
        card1: { type: 1, cards: [...order], criticalStar: 5, more_or_less: true },
        card2: { type: 1, cards: [...order], criticalStar: 5, more_or_less: true },
        card3: { type: 1, cards: [...order], criticalStar: 0, more_or_less: true },
        breakpoint: [false, false],
        colorFirst: false,
      };
    },
  },
];

export function formatCardTokenLabel(token, type, tr = (k) => k) {
  if (type === 0) {
    return `${tr("NP")} ${token}`;
  }
  const text = String(token);
  const match = /^([1-3])([ABQ])(S\d+)?$/.exec(text);
  if (match) {
    const [, slot, color, special] = match;
    const suffix = special ? `·${special}` : "";
    return `${slot}${color}${suffix}`;
  }
  return text;
}

export function cardTokenClass(token, type) {
  if (type === 0) return "card-np";
  const text = String(token);
  const match = /^[1-3]([ABQ])/.exec(text);
  if (match && COLOR_META[match[1]]) return COLOR_META[match[1]].cls;
  return "card-special";
}

export function toggleCardPreference(cards, token) {
  const list = Array.isArray(cards) ? [...cards] : [];
  const idx = list.indexOf(token);
  if (idx >= 0) {
    if (list.length <= 1) return list; // keep at least 1 card preference
    list.splice(idx, 1);
  } else {
    list.push(token);
  }
  return list;
}

export function moveCardPreference(cards, index, delta) {
  const list = Array.isArray(cards) ? [...cards] : [];
  const next = index + delta;
  if (index < 0 || index >= list.length || next < 0 || next >= list.length) return list;
  const [item] = list.splice(index, 1);
  list.splice(next, 0, item);
  return list;
}

export function createVisualStrategyEnhancer({
  fieldset,
  cardRows,
  getEntriesState,
  applyStrategyMutation,
  translate = (k) => k,
}) {
  const t = translate;
  let mainAttackerSlot = 1;

  // Build Quick Template Bar once at the top of .preset-strategy-fields
  const fieldsHost = fieldset?.querySelector(".preset-strategy-fields");
  const templateBar = document.createElement("div");
  templateBar.className = "strategy-quick-bar";
  templateBar.hidden = true;
  if (fieldsHost) {
    fieldsHost.prepend(templateBar);
  }

  // Create visual builder host inside each strategy-card-row
  const cardHosts = new Map();
  for (const row of cardRows) {
    const cardKey = row.dataset.strategyCard;
    const host = document.createElement("div");
    host.className = "strategy-card-visual";
    host.dataset.strategyVisualCard = cardKey;
    row.append(host);
    cardHosts.set(cardKey, host);
  }

  function renderTemplateBar(disabled, hasValidStrategy) {
    templateBar.hidden = !hasValidStrategy;
    if (!hasValidStrategy) return;
    const frag = document.createDocumentFragment();

    const header = document.createElement("div");
    header.className = "strategy-quick-head";
    const title = document.createElement("span");
    title.className = "strategy-quick-title";
    title.textContent = t("Quick Templates");
    header.append(title);

    const slotGroup = document.createElement("div");
    slotGroup.className = "strategy-quick-slots";
    const slotLbl = document.createElement("span");
    slotLbl.className = "strategy-quick-slot-label";
    slotLbl.textContent = t("Main attacker");
    slotGroup.append(slotLbl);
    for (const s of [1, 2, 3]) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `chip-button${mainAttackerSlot === s ? " active" : ""}`;
      btn.textContent = t("Slot {slot}", { slot: s });
      btn.disabled = disabled;
      btn.addEventListener("click", () => {
        mainAttackerSlot = s;
        render();
      });
      slotGroup.append(btn);
    }
    header.append(slotGroup);
    frag.append(header);

    const chips = document.createElement("div");
    chips.className = "strategy-quick-chips";
    for (const tpl of STRATEGY_QUICK_TEMPLATES) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip-button strategy-tpl-btn";
      btn.dataset.strategyTemplate = tpl.id;
      btn.textContent = t(tpl.labelKey);
      btn.disabled = disabled;
      btn.addEventListener("click", () => {
        applyStrategyMutation((entry) => {
          entry.strategy = tpl.build(mainAttackerSlot);
        });
      });
      chips.append(btn);
    }
    frag.append(chips);
    templateBar.replaceChildren(frag);
  }

  function renderCardVisual(cardKey, spec, disabled) {
    const host = cardHosts.get(cardKey);
    if (!host) return;
    if (!spec || typeof spec !== "object" || Array.isArray(spec) || spec.type === 2 || ![0, 1].includes(spec.type)) {
      host.hidden = true;
      host.replaceChildren();
      return;
    }
    host.hidden = false;
    const type = spec.type;
    const cards = Array.isArray(spec.cards) ? spec.cards : [];
    const frag = document.createDocumentFragment();

    // 1. Ordered Priority Queue
    const queueRow = document.createElement("div");
    queueRow.className = "strategy-priority-queue";
    const qLabel = document.createElement("span");
    qLabel.className = "strategy-visual-label";
    qLabel.textContent = t("Priority");
    queueRow.append(qLabel);

    const pillsWrap = document.createElement("div");
    pillsWrap.className = "strategy-priority-pills";
    cards.forEach((token, idx) => {
      const pill = document.createElement("span");
      pill.className = `strategy-card-pill ${cardTokenClass(token, type)}`;
      const rank = document.createElement("span");
      rank.className = "pill-rank";
      rank.textContent = String(idx + 1);
      const lbl = document.createElement("span");
      lbl.className = "pill-code";
      lbl.textContent = formatCardTokenLabel(token, type, t);
      pill.append(rank, lbl);

      if (cards.length > 1) {
        const leftBtn = document.createElement("button");
        leftBtn.type = "button";
        leftBtn.className = "pill-act";
        leftBtn.textContent = "‹";
        leftBtn.title = t("Move earlier");
        leftBtn.disabled = disabled || idx === 0;
        leftBtn.addEventListener("click", () => {
          applyStrategyMutation((entry) => {
            entry.strategy[cardKey].cards = moveCardPreference(entry.strategy[cardKey].cards, idx, -1);
          });
        });

        const rightBtn = document.createElement("button");
        rightBtn.type = "button";
        rightBtn.className = "pill-act";
        rightBtn.textContent = "›";
        rightBtn.title = t("Move later");
        rightBtn.disabled = disabled || idx === cards.length - 1;
        rightBtn.addEventListener("click", () => {
          applyStrategyMutation((entry) => {
            entry.strategy[cardKey].cards = moveCardPreference(entry.strategy[cardKey].cards, idx, 1);
          });
        });

        const rmBtn = document.createElement("button");
        rmBtn.type = "button";
        rmBtn.className = "pill-act pill-rm";
        rmBtn.textContent = "×";
        rmBtn.title = t("Remove");
        rmBtn.disabled = disabled;
        rmBtn.addEventListener("click", () => {
          applyStrategyMutation((entry) => {
            const next = [...entry.strategy[cardKey].cards];
            next.splice(idx, 1);
            entry.strategy[cardKey].cards = next;
          });
        });
        pill.append(leftBtn, rightBtn, rmBtn);
      }
      pillsWrap.append(pill);
    });
    queueRow.append(pillsWrap);

    if (cardKey === "card2" || cardKey === "card1") {
      const targetCard = cardKey === "card1" ? "card2" : "card3";
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "chip-button strategy-copy-next";
      copyBtn.textContent = cardKey === "card1" ? t("Copy → Card 2") : t("Copy → Card 3");
      copyBtn.disabled = disabled;
      copyBtn.addEventListener("click", () => {
        applyStrategyMutation((entry) => {
          entry.strategy[targetCard] = structuredClone(entry.strategy[cardKey]);
        });
      });
      queueRow.append(copyBtn);
    }
    frag.append(queueRow);

    // 2. Clickable Palette
    const palette = document.createElement("div");
    palette.className = "strategy-card-palette";
    if (type === 0) {
      for (const slot of [1, 2, 3]) {
        const rankIdx = cards.indexOf(slot);
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `strategy-pal-btn card-np${rankIdx >= 0 ? " active" : ""}`;
        btn.dataset.cardToken = String(slot);
        btn.textContent = `${rankIdx >= 0 ? `#${rankIdx + 1} ` : ""}${t("Servant {slot}", { slot })} ${t("NP")}`;
        btn.disabled = disabled;
        btn.addEventListener("click", () => {
          applyStrategyMutation((entry) => {
            entry.strategy[cardKey].cards = toggleCardPreference(entry.strategy[cardKey].cards, slot);
          });
        });
        palette.append(btn);
      }
    } else {
      for (const slot of [1, 2, 3]) {
        const group = document.createElement("div");
        group.className = "strategy-pal-group";
        for (const color of COLOR_ORDER) {
          const code = `${slot}${color}`;
          const rankIdx = cards.indexOf(code);
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = `strategy-pal-btn ${COLOR_META[color].cls}${rankIdx >= 0 ? " active" : ""}`;
          btn.dataset.cardToken = code;
          btn.textContent = `${rankIdx >= 0 ? `#${rankIdx + 1} ` : ""}${code}`;
          btn.title = `${t("Slot {slot}", { slot })} ${t(COLOR_META[color].labelKey)}`;
          btn.disabled = disabled;
          btn.addEventListener("click", () => {
            applyStrategyMutation((entry) => {
              entry.strategy[cardKey].cards = toggleCardPreference(entry.strategy[cardKey].cards, code);
            });
          });
          group.append(btn);
        }
        palette.append(group);
      }
      const quickTools = document.createElement("div");
      quickTools.className = "strategy-pal-tools";
      for (const [labelKey, orderFn] of [
        ["Fill B→A→Q", () => buildAllCardsByColorOrder("B")],
        ["Fill Main First", () => buildMainAttackerOrder(mainAttackerSlot, "B")],
        ["+ Weak (S0)", () => toggleCardPreference(cards, "S0")],
      ]) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "chip-button";
        btn.textContent = t(labelKey);
        btn.disabled = disabled;
        btn.addEventListener("click", () => {
          applyStrategyMutation((entry) => {
            entry.strategy[cardKey].cards = orderFn();
          });
        });
        quickTools.append(btn);
      }
      palette.append(quickTools);
    }
    frag.append(palette);
    host.replaceChildren(frag);
  }

  function render() {
    const info = getEntriesState();
    if (!info || !info.isStrategy) {
      templateBar.hidden = true;
      cardHosts.forEach((host) => {
        host.hidden = true;
        host.replaceChildren();
      });
      return;
    }
    const { strategy, disabled } = info;
    const validStrategy = Boolean(strategy && typeof strategy === "object" && !Array.isArray(strategy));
    renderTemplateBar(disabled, validStrategy);
    for (const cardKey of ["card1", "card2", "card3"]) {
      renderCardVisual(cardKey, validStrategy ? strategy[cardKey] : null, disabled);
    }
  }

  return { render };
}
