const state = {
  pages: [],
  currentPageId: null,
  currentPage: null,
  currentResult: null,
  currentDetection: null,
  currentOcr: null,
  selectedBubbleIndex: null,
  dragMode: null,
  dragBubbleIndex: null,
  dragStart: null,
  dragOriginCoords: null,
  view: "source",
};

const elements = {
  folderInput: document.getElementById("folderInput"),
  pageList: document.getElementById("pageList"),
  pageImage: document.getElementById("pageImage"),
  overlay: document.getElementById("overlay"),
  ocrResultList: document.getElementById("ocrResultList"),
  bubbleEditorPanel: document.getElementById("bubbleEditorPanel"),
  timingPanel: document.getElementById("timingPanel"),
  debugPanel: document.getElementById("debugPanel"),
  statusText: document.getElementById("statusText"),
  readTextBtn: document.getElementById("readTextBtn"),
  runPageBtn: document.getElementById("runPageBtn"),
  redoInpaintBtn: document.getElementById("redoInpaintBtn"),
  redoRenderBtn: document.getElementById("redoRenderBtn"),
  showSourceBtn: document.getElementById("showSourceBtn"),
  showTranslatedBtn: document.getElementById("showTranslatedBtn"),
};

function setStatus(text) {
  if (elements.statusText) {
    elements.statusText.textContent = text;
  }
}

function getTotalTimingText() {
  const totalSeconds = Number(state.currentResult?.timings?.total || 0);
  if (totalSeconds <= 0) {
    return "";
  }
  return `当前页总耗时 ${totalSeconds.toFixed(2)}s`;
}

function setStatusWithTiming(prefix) {
  const totalText = getTotalTimingText();
  setStatus(totalText ? `${prefix} · ${totalText}` : prefix);
}

function applyCurrentResult(result) {
  state.currentResult = result;
  state.currentDetection = extractDetection(result);
  state.currentOcr = extractOcr(result);
  normalizeSelectedBubbleIndex();
  renderBubbleEditorPanel();
  renderTimingPanel();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function requestJson(url, options) {
  const response = await fetch(url, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    payload = null;
  }
  if (!response.ok) {
    const message = payload?.error || `请求失败: ${response.status}`;
    throw new Error(message);
  }
  return payload || {};
}

function getBubbleStates() {
  const bubbleStates = state.currentResult?.bubbleStates || state.currentResult?.bubbles || [];
  if (bubbleStates.length > 0) {
    return bubbleStates;
  }

  const bubbleCoords = state.currentDetection?.bubbleCoords || [];
  const bubblePolygons = state.currentDetection?.bubblePolygons || [];
  const directions = state.currentDetection?.autoDirections || [];
  const originalTexts = state.currentOcr?.originalTexts || [];
  const ocrResults = state.currentOcr?.ocrResults || [];
  return bubbleCoords.map((coords, index) => ({
    coords,
    polygon: bubblePolygons[index] || [],
    direction: directions[index] || "vertical",
    textDirection: directions[index] || "vertical",
    autoTextDirection: directions[index] || "vertical",
    originalText: originalTexts[index] || "",
    translatedText: "",
    ocrResult: ocrResults[index] || {},
  }));
}

function normalizeSelectedBubbleIndex() {
  const bubbles = getBubbleStates();
  if (state.selectedBubbleIndex == null) {
    return;
  }
  if (!bubbles[state.selectedBubbleIndex]) {
    state.selectedBubbleIndex = null;
  }
}

function getSelectedBubble() {
  if (state.selectedBubbleIndex == null) {
    return null;
  }
  return getBubbleStates()[state.selectedBubbleIndex] || null;
}

async function refreshPages({ autoSelect = true } = {}) {
  const data = await requestJson("/api/library/pages");
  state.pages = data.pages || [];
  renderPageList();

  if (!autoSelect) {
    return;
  }

  if (state.currentPageId) {
    const exists = state.pages.some((page) => page.id === state.currentPageId);
    if (exists) {
      await loadPage(state.currentPageId);
      return;
    }
  }

  if (state.pages.length > 0) {
    await loadPage(state.pages[0].id);
    return;
  }

  resetPageState();
  renderCurrentPage();
  renderOcrResults();
  renderBubbleEditorPanel();
  renderTimingPanel();
  renderDebugPanel();
}

async function importFolder(files) {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file, file.name);
  }

  setStatus(`正在导入 ${files.length} 张图片`);
  const data = await requestJson("/api/library/import", {
    method: "POST",
    body: form,
  });
  await refreshPages({ autoSelect: false });

  if ((data.pages || []).length > 0) {
    await loadPage(data.pages[0].id);
  }

  setStatus(`导入完成，共 ${data.imported || 0} 张`);
}

function resetPageState() {
  state.currentPageId = null;
  state.currentPage = null;
  state.currentResult = null;
  state.currentDetection = null;
  state.currentOcr = null;
  state.selectedBubbleIndex = null;
  state.dragMode = null;
  state.dragBubbleIndex = null;
  state.dragStart = null;
  state.dragOriginCoords = null;
}

async function loadPage(pageId, { selectedBubbleIndex = null, preferredView = "source" } = {}) {
  if (!pageId) {
    return;
  }

  state.currentPageId = pageId;
  state.currentResult = null;
  state.currentDetection = null;
  state.currentOcr = null;
  state.selectedBubbleIndex = selectedBubbleIndex;
  state.dragMode = null;
  state.dragBubbleIndex = null;
  state.dragStart = null;
  state.dragOriginCoords = null;
  state.view = preferredView;

  const detail = await requestJson(`/api/library/page/${pageId}`);
  state.currentPage = detail.page;
  renderPageList();

  const resultPayload = await requestJson(`/api/page/${pageId}/result`);
  if (resultPayload.result) {
    applyCurrentResult(resultPayload.result);
  }

  renderCurrentPage();
  renderOcrResults();
  renderBubbleEditorPanel();
  renderTimingPanel();
  renderDebugPanel();
  setStatusWithTiming(`已加载 ${state.currentPage.fileName}`);
}

function extractDetection(payload) {
  const bubbleCoords = payload?.bubbleCoords || [];
  if (bubbleCoords.length === 0) {
    return null;
  }
  return {
    bubbleCoords,
    bubblePolygons: payload.bubblePolygons || [],
    autoDirections: payload.autoDirections || [],
    textlinesPerBubble: payload.textlinesPerBubble || [],
  };
}

function extractOcr(payload) {
  const originalTexts = payload?.originalTexts || [];
  const ocrResults = payload?.ocrResults || [];
  if (originalTexts.length === 0 && ocrResults.length === 0) {
    return null;
  }
  return {
    originalTexts,
    ocrResults,
  };
}

function getCurrentImageUrl() {
  if (!state.currentPage) {
    return "";
  }
  if (state.view === "translated" && state.currentPage.translatedUrl) {
    return state.currentPage.translatedUrl;
  }
  return state.currentPage.sourceUrl;
}

function renderCurrentPage() {
  const imageUrl = getCurrentImageUrl();
  if (!imageUrl) {
    elements.pageImage.removeAttribute("src");
    clearOverlay();
    return;
  }
  elements.pageImage.src = `${imageUrl}?ts=${Date.now()}`;
}

function renderPageList() {
  if (!elements.pageList) {
    return;
  }

  if (state.pages.length === 0) {
    elements.pageList.innerHTML = '<p class="ocr-empty">导入目录后，这里会列出页面。</p>';
    return;
  }

  elements.pageList.innerHTML = state.pages
    .map((page) => {
      const isActive = page.id === state.currentPageId;
      const flag = page.hasCache ? "已缓存" : "未处理";
      return `
        <button class="page-item${isActive ? " is-active" : ""}" data-page-id="${page.id}">
          <strong>${escapeHtml(page.fileName)}</strong><br />
          <span>${escapeHtml(flag)}</span>
        </button>
      `;
    })
    .join("");
}

function renderOcrResults() {
  if (!elements.ocrResultList) {
    return;
  }

  const texts = state.currentOcr?.originalTexts || [];
  const directions = state.currentDetection?.autoDirections || [];
  if (texts.length === 0) {
    elements.ocrResultList.innerHTML =
      '<p class="ocr-empty">选择页面后点击“读取文字”，这里会显示 OCR 结果。</p>';
    return;
  }

  elements.ocrResultList.innerHTML = texts
    .map((text, index) => {
      const direction = directions[index] || "unknown";
      return `
        <article class="ocr-item">
          <div class="ocr-item-header">
            <span>气泡 ${index + 1}</span>
            <span>${escapeHtml(direction)}</span>
          </div>
          <p class="ocr-item-text">${escapeHtml(text || "(空)")}</p>
        </article>
      `;
    })
    .join("");
}

function renderBubbleEditorPanel() {
  if (!elements.bubbleEditorPanel) {
    return;
  }

  const selectedBubble = getSelectedBubble();
  if (!selectedBubble) {
    elements.bubbleEditorPanel.innerHTML =
      '<p class="ocr-empty">点击画面中的框后，这里会显示当前气泡信息。</p>';
    return;
  }

  const direction =
    selectedBubble.textDirection || selectedBubble.autoTextDirection || selectedBubble.direction || "unknown";
  const textAlign = selectedBubble.textAlign || "start";
  const coords = Array.isArray(selectedBubble.coords) ? selectedBubble.coords.join(", ") : "";
  elements.bubbleEditorPanel.innerHTML = `
    <article class="bubble-card">
      <div class="ocr-item-header">
        <span>气泡 ${state.selectedBubbleIndex + 1}</span>
        <span>${escapeHtml(direction)}</span>
      </div>
      <div class="bubble-field">
        <label>原文</label>
        <pre>${escapeHtml(selectedBubble.originalText || "(空)")}</pre>
      </div>
      <div class="bubble-field">
        <label for="bubbleTranslatedTextInput">译文</label>
        <textarea id="bubbleTranslatedTextInput" rows="6">${escapeHtml(selectedBubble.translatedText || "")}</textarea>
      </div>
      <div class="bubble-form-grid">
        <div class="bubble-field">
          <label for="bubbleFontSizeInput">字号</label>
          <input id="bubbleFontSizeInput" type="number" min="1" value="${selectedBubble.fontSize ?? ""}" placeholder="留空自动" />
        </div>
        <div class="bubble-field">
          <label for="bubbleTextDirectionInput">排版</label>
          <select id="bubbleTextDirectionInput">
            <option value="vertical"${direction === "vertical" ? " selected" : ""}>竖排</option>
            <option value="horizontal"${direction === "horizontal" ? " selected" : ""}>横排</option>
          </select>
        </div>
        <div class="bubble-field">
          <label for="bubbleLineSpacingInput">行距</label>
          <input id="bubbleLineSpacingInput" type="number" min="0.5" step="0.05" value="${selectedBubble.lineSpacing ?? ""}" />
        </div>
        <div class="bubble-field">
          <label for="bubbleTextAlignInput">对齐</label>
          <select id="bubbleTextAlignInput">
            <option value="start"${textAlign === "start" ? " selected" : ""}>起始</option>
            <option value="center"${textAlign === "center" ? " selected" : ""}>居中</option>
            <option value="end"${textAlign === "end" ? " selected" : ""}>末端</option>
          </select>
        </div>
      </div>
      <div class="bubble-geometry">框坐标: ${escapeHtml(coords || "(空)")}</div>
      <div class="bubble-actions">
        <button id="saveBubbleBtn" type="button">保存当前框</button>
        <button id="rerenderBubbleBtn" type="button">重排当前框</button>
      </div>
    </article>
  `;
}

function renderTimingPanel() {
  if (!elements.timingPanel) {
    return;
  }

  const timings = state.currentResult?.timings || null;
  if (!timings) {
    elements.timingPanel.innerHTML = '<p class="ocr-empty">当前页还没有耗时数据。</p>';
    return;
  }

  const labels = {
    detect: "检测",
    ocr: "OCR",
    translate: "翻译",
    color: "取色",
    inpaint: "擦字",
    render: "写字",
    saveBubble: "保存当前框",
    rerenderBubble: "单框重排",
    redoInpaint: "重做擦字",
    redoRender: "重做写字",
    total: "总计",
  };
  const orderedKeys = [
    "detect",
    "ocr",
    "translate",
    "color",
    "inpaint",
    "render",
    "saveBubble",
    "rerenderBubble",
    "redoInpaint",
    "redoRender",
    "total",
  ];
  elements.timingPanel.innerHTML = orderedKeys
    .filter((key) => key in timings)
    .map((key) => {
      const value = Number(timings[key] || 0);
      return `
        <div class="timing-item">
          <span>${escapeHtml(labels[key] || key)}</span>
          <strong>${value.toFixed(2)}s</strong>
        </div>
      `;
    })
    .join("");

  if (getTotalTimingText() && (!elements.statusText?.textContent || elements.statusText.textContent.startsWith("已加载 "))) {
    setStatus(getTotalTimingText());
  }
}

function renderDebugPanel() {
  if (!elements.debugPanel) {
    return;
  }

  elements.debugPanel.textContent = JSON.stringify(
    {
      page: state.currentPage,
      result: state.currentResult,
    },
    null,
    2,
  );
}

function getBubbleCanvasRect(coords) {
  const image = elements.pageImage;
  const canvas = elements.overlay;
  if (!image?.naturalWidth || !image?.naturalHeight || !canvas || !Array.isArray(coords) || coords.length < 4) {
    return null;
  }

  const scaleX = canvas.width / image.naturalWidth;
  const scaleY = canvas.height / image.naturalHeight;
  const [x1, y1, x2, y2] = coords;
  return {
    left: x1 * scaleX,
    top: y1 * scaleY,
    right: x2 * scaleX,
    bottom: y2 * scaleY,
    width: (x2 - x1) * scaleX,
    height: (y2 - y1) * scaleY,
  };
}

function hitTestBubble(offsetX, offsetY) {
  const bubbles = getBubbleStates();
  if (bubbles.length === 0) {
    return null;
  }

  for (let index = bubbles.length - 1; index >= 0; index -= 1) {
    const coords = bubbles[index]?.coords;
    const rect = getBubbleCanvasRect(coords);
    if (!rect) {
      continue;
    }
    if (offsetX >= rect.left && offsetX <= rect.right && offsetY >= rect.top && offsetY <= rect.bottom) {
      return index;
    }
  }

  return null;
}

function hitTestResizeHandle(offsetX, offsetY, coords) {
  const rect = getBubbleCanvasRect(coords);
  if (!rect) {
    return false;
  }
  const handleSize = 14;
  return offsetX >= rect.right - handleSize && offsetX <= rect.right && offsetY >= rect.bottom - handleSize && offsetY <= rect.bottom;
}

function clampBubbleCoords(coords) {
  const image = elements.pageImage;
  const maxX = image?.naturalWidth || coords[2] || 0;
  const maxY = image?.naturalHeight || coords[3] || 0;
  let [x1, y1, x2, y2] = coords.map((value) => Math.round(value));
  x1 = Math.max(0, Math.min(x1, Math.max(0, maxX - 12)));
  y1 = Math.max(0, Math.min(y1, Math.max(0, maxY - 12)));
  x2 = Math.max(x1 + 12, Math.min(x2, maxX));
  y2 = Math.max(y1 + 12, Math.min(y2, maxY));
  return [x1, y1, x2, y2];
}

function applyBubblePatchLocally(bubbleIndex, patch) {
  const result = state.currentResult;
  const bubble = getBubbleStates()[bubbleIndex];
  if (!result || !bubble) {
    return;
  }

  const nextBubble = { ...bubble, ...patch };
  const bubbleStates = getBubbleStates().map((item, index) => (index === bubbleIndex ? nextBubble : item));
  result.bubbleStates = bubbleStates;
  result.bubbles = bubbleStates;

  if (Array.isArray(result.bubbleCoords) && patch.coords) {
    result.bubbleCoords = result.bubbleCoords.map((coords, index) => (index === bubbleIndex ? patch.coords : coords));
  }
  if (Array.isArray(result.translatedTexts) && Object.prototype.hasOwnProperty.call(patch, "translatedText")) {
    result.translatedTexts = result.translatedTexts.map((text, index) =>
      index === bubbleIndex ? patch.translatedText : text,
    );
  }

  state.currentDetection = extractDetection(result);
  state.currentOcr = extractOcr(result);
}

function clearOverlay() {
  if (!elements.overlay) {
    return;
  }
  const context = elements.overlay.getContext("2d");
  context.clearRect(0, 0, elements.overlay.width, elements.overlay.height);
}

function syncOverlay() {
  const image = elements.pageImage;
  const canvas = elements.overlay;
  if (!image || !canvas || !image.naturalWidth || !image.naturalHeight) {
    clearOverlay();
    return;
  }

  const width = image.clientWidth;
  const height = image.clientHeight;
  canvas.width = width;
  canvas.height = height;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  drawOverlay();
}

function drawOverlay() {
  const image = elements.pageImage;
  const canvas = elements.overlay;
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, canvas.width, canvas.height);

  const bubbles = getBubbleStates();
  if (!image.naturalWidth || !image.naturalHeight || bubbles.length === 0) {
    return;
  }

  const scaleX = canvas.width / image.naturalWidth;
  const scaleY = canvas.height / image.naturalHeight;

  context.lineWidth = 2;
  context.font = "16px sans-serif";

  bubbles.forEach((bubble, index) => {
    const coords = bubble.coords;
    if (!Array.isArray(coords) || coords.length < 4) {
      return;
    }

    const isSelected = index === state.selectedBubbleIndex;
    const [x1, y1, x2, y2] = coords;
    const left = x1 * scaleX;
    const top = y1 * scaleY;
    const width = (x2 - x1) * scaleX;
    const height = (y2 - y1) * scaleY;

    context.strokeStyle = isSelected ? "rgba(35, 104, 160, 0.98)" : "rgba(163, 58, 43, 0.95)";
    context.fillStyle = isSelected ? "rgba(35, 104, 160, 0.20)" : "rgba(163, 58, 43, 0.16)";
    context.fillRect(left, top, width, height);
    context.strokeRect(left, top, width, height);

    const label = String(index + 1);
    const labelWidth = context.measureText(label).width + 12;
    context.fillStyle = "rgba(22, 19, 15, 0.92)";
    context.fillRect(left, Math.max(0, top - 22), labelWidth, 20);
    context.fillStyle = "#fffaf1";
    context.fillText(label, left + 6, Math.max(14, top - 7));

    if (isSelected) {
      context.fillStyle = "rgba(35, 104, 160, 0.98)";
      context.fillRect(left + width - 10, top + height - 10, 10, 10);
    }
  });
}

function collectBubblePatchFromForm() {
  const selectedBubble = getSelectedBubble();
  if (!selectedBubble) {
    return {};
  }

  const translatedText = document.getElementById("bubbleTranslatedTextInput")?.value ?? "";
  const fontSizeValue = (document.getElementById("bubbleFontSizeInput")?.value || "").trim();
  const lineSpacingValue = (document.getElementById("bubbleLineSpacingInput")?.value || "").trim();
  const textDirection =
    document.getElementById("bubbleTextDirectionInput")?.value ||
    selectedBubble.textDirection ||
    selectedBubble.direction ||
    "vertical";
  const textAlign = document.getElementById("bubbleTextAlignInput")?.value || selectedBubble.textAlign || "start";

  const patch = {
    translatedText,
    textDirection,
    textAlign,
  };
  patch.fontSize = fontSizeValue ? Number(fontSizeValue) : null;
  if (lineSpacingValue) {
    patch.lineSpacing = Number(lineSpacingValue);
  }
  return patch;
}

async function saveSelectedBubble(patch = collectBubblePatchFromForm(), successText = "当前框已保存") {
  if (!state.currentPageId || state.selectedBubbleIndex == null) {
    setStatus("请先选择一个气泡");
    return null;
  }

  setStatus("正在保存当前框");
  const result = await requestJson("/api/pipeline/update-bubble", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pageId: state.currentPageId,
      bubbleIndex: state.selectedBubbleIndex,
      patch,
    }),
  });
  applyCurrentResult(result);
  renderDebugPanel();
  syncOverlay();
  setStatusWithTiming(successText);
  return result;
}

async function rerenderSelectedBubble() {
  if (!state.currentPageId || state.selectedBubbleIndex == null) {
    setStatus("请先选择一个气泡");
    return;
  }

  await saveSelectedBubble(collectBubblePatchFromForm(), "当前框已保存，准备重排");
  const selectedBubbleIndex = state.selectedBubbleIndex;
  setStatus("正在重排当前框");
  const result = await requestJson("/api/pipeline/rerender-bubble", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pageId: state.currentPageId,
      bubbleIndex: selectedBubbleIndex,
    }),
  });

  applyCurrentResult(result);
  await loadPage(state.currentPageId, {
    selectedBubbleIndex,
    preferredView: "translated",
  });
  if (state.currentPage?.translatedUrl) {
    state.view = "translated";
    renderCurrentPage();
  }
  setStatusWithTiming("当前框重排完成");
}

function handleOverlayPointerDown(event) {
  const hitIndex = hitTestBubble(event.offsetX, event.offsetY);
  state.selectedBubbleIndex = hitIndex;
  renderBubbleEditorPanel();
  drawOverlay();

  if (hitIndex == null) {
    return;
  }

  const targetBubble = getBubbleStates()[hitIndex];
  if (!targetBubble?.coords) {
    return;
  }

  state.dragBubbleIndex = hitIndex;
  state.dragStart = { x: event.clientX, y: event.clientY };
  state.dragOriginCoords = [...targetBubble.coords];
  state.dragMode = hitTestResizeHandle(event.offsetX, event.offsetY, targetBubble.coords) ? "resize" : "move";
  elements.overlay?.setPointerCapture?.(event.pointerId);
  event.preventDefault();
}

function handleOverlayPointerMove(event) {
  if (!state.dragMode || state.dragBubbleIndex == null || !state.dragOriginCoords || !state.dragStart) {
    return;
  }

  const image = elements.pageImage;
  const canvas = elements.overlay;
  if (!image?.naturalWidth || !canvas?.width) {
    return;
  }

  const scaleX = image.naturalWidth / canvas.width;
  const scaleY = image.naturalHeight / canvas.height;
  const deltaX = (event.clientX - state.dragStart.x) * scaleX;
  const deltaY = (event.clientY - state.dragStart.y) * scaleY;
  const [x1, y1, x2, y2] = state.dragOriginCoords;

  let nextCoords;
  if (state.dragMode === "resize") {
    nextCoords = clampBubbleCoords([x1, y1, x2 + deltaX, y2 + deltaY]);
  } else {
    nextCoords = clampBubbleCoords([x1 + deltaX, y1 + deltaY, x2 + deltaX, y2 + deltaY]);
  }

  applyBubblePatchLocally(state.dragBubbleIndex, { coords: nextCoords });
  drawOverlay();
  renderDebugPanel();
}

async function handleOverlayPointerUp() {
  if (!state.dragMode || state.dragBubbleIndex == null) {
    state.dragMode = null;
    state.dragBubbleIndex = null;
    state.dragStart = null;
    state.dragOriginCoords = null;
    return;
  }

  const bubbleIndex = state.dragBubbleIndex;
  const bubble = getBubbleStates()[bubbleIndex];
  const savedCoords = Array.isArray(bubble?.coords) ? [...bubble.coords] : null;
  const dragMode = state.dragMode;

  state.dragMode = null;
  state.dragBubbleIndex = null;
  state.dragStart = null;
  state.dragOriginCoords = null;

  if (!savedCoords) {
    return;
  }

  try {
    await saveSelectedBubble({ coords: savedCoords }, dragMode === "resize" ? "当前框尺寸已更新" : "当前框位置已更新");
  } catch (error) {
    setStatus(`更新框失败：${error.message}`);
  }
}

async function readCurrentPageText() {
  if (!state.currentPageId) {
    setStatus("请先导入并选择页面");
    return;
  }

  setStatus("正在检测气泡");
  const detection = await requestJson("/api/pipeline/detect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pageId: state.currentPageId }),
  });

  state.currentDetection = detection;
  state.currentResult = { ...(state.currentResult || {}), ...detection };
  renderDebugPanel();
  syncOverlay();

  const bubbleCount = detection.bubbleCoords?.length || 0;
  if (bubbleCount === 0) {
    state.currentOcr = { originalTexts: [], ocrResults: [] };
    renderOcrResults();
    setStatus("未检测到可识别气泡");
    return;
  }

  setStatus(`检测完成，开始 OCR（${bubbleCount} 个气泡）`);
  const ocr = await requestJson("/api/pipeline/ocr", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pageId: state.currentPageId,
      bubbleCoords: detection.bubbleCoords,
      bubblePolygons: detection.bubblePolygons || [],
      autoDirections: detection.autoDirections || [],
      textlinesPerBubble: detection.textlinesPerBubble || [],
    }),
  });

  applyCurrentResult({ ...(state.currentResult || {}), ...ocr });
  renderOcrResults();
  renderDebugPanel();
  syncOverlay();
  setStatus(`OCR 完成，识别 ${ocr.originalTexts?.length || 0} 个气泡`);
}

async function runCurrentPage() {
  if (!state.currentPageId) {
    setStatus("请先导入并选择页面");
    return;
  }

  setStatus("正在执行整页流水线");
  const result = await requestJson("/api/pipeline/run-page", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pageId: state.currentPageId }),
  });

  applyCurrentResult(result);
  await loadPage(state.currentPageId, { preferredView: "translated" });
  setStatusWithTiming("整页流水线完成");
}

async function redoCurrentInpaint() {
  if (!state.currentPageId) {
    setStatus("请先导入并选择页面");
    return;
  }

  setStatus("正在重做擦字");
  const result = await requestJson("/api/pipeline/redo-inpaint", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pageId: state.currentPageId }),
  });

  applyCurrentResult(result);
  await loadPage(state.currentPageId, {
    selectedBubbleIndex: state.selectedBubbleIndex,
    preferredView: state.view,
  });
  setStatusWithTiming("擦字完成");
}

async function redoCurrentRender() {
  if (!state.currentPageId) {
    setStatus("请先导入并选择页面");
    return;
  }

  setStatus("正在重做写字");
  const result = await requestJson("/api/pipeline/redo-render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pageId: state.currentPageId }),
  });

  applyCurrentResult(result);
  await loadPage(state.currentPageId, {
    selectedBubbleIndex: state.selectedBubbleIndex,
    preferredView: "translated",
  });
  setStatusWithTiming("写字完成");
}

function bindEvents() {
  elements.folderInput?.addEventListener("change", async (event) => {
    const files = Array.from(event.target.files || []);
    if (files.length === 0) {
      return;
    }

    try {
      await importFolder(files);
    } catch (error) {
      setStatus(`导入失败：${error.message}`);
    } finally {
      event.target.value = "";
    }
  });

  elements.pageList?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-page-id]");
    if (!button) {
      return;
    }

    try {
      await loadPage(button.dataset.pageId);
    } catch (error) {
      setStatus(`加载页面失败：${error.message}`);
    }
  });

  elements.overlay?.addEventListener("pointerdown", handleOverlayPointerDown);
  window.addEventListener("pointermove", handleOverlayPointerMove);
  window.addEventListener("pointerup", handleOverlayPointerUp);

  elements.bubbleEditorPanel?.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }

    try {
      if (target.id === "saveBubbleBtn") {
        await saveSelectedBubble();
      }
      if (target.id === "rerenderBubbleBtn") {
        await rerenderSelectedBubble();
      }
    } catch (error) {
      const actionText = target.id === "rerenderBubbleBtn" ? "重排当前框" : "保存当前框";
      setStatus(`${actionText}失败：${error.message}`);
    }
  });

  elements.readTextBtn?.addEventListener("click", async () => {
    try {
      await readCurrentPageText();
    } catch (error) {
      setStatus(`读取文字失败：${error.message}`);
    }
  });

  elements.runPageBtn?.addEventListener("click", async () => {
    try {
      await runCurrentPage();
    } catch (error) {
      setStatus(`整页翻译失败：${error.message}`);
    }
  });

  elements.showSourceBtn?.addEventListener("click", () => {
    state.view = "source";
    renderCurrentPage();
    setStatus("显示原图");
  });

  elements.showTranslatedBtn?.addEventListener("click", () => {
    if (!state.currentPage?.translatedUrl) {
      setStatus("当前页面还没有译图");
      return;
    }
    state.view = "translated";
    renderCurrentPage();
    setStatus("显示译图");
  });

  elements.redoInpaintBtn?.addEventListener("click", async () => {
    try {
      await redoCurrentInpaint();
    } catch (error) {
      setStatus(`重做擦字失败：${error.message}`);
    }
  });

  elements.redoRenderBtn?.addEventListener("click", async () => {
    try {
      await redoCurrentRender();
    } catch (error) {
      setStatus(`重做写字失败：${error.message}`);
    }
  });

  elements.pageImage?.addEventListener("load", syncOverlay);
  window.addEventListener("resize", syncOverlay);
}

async function bootstrap() {
  bindEvents();
  try {
    await refreshPages();
    if (state.pages.length === 0) {
      setStatus("等待导入页面");
    }
  } catch (error) {
    setStatus(`初始化失败：${error.message}`);
  }
}

bootstrap();
