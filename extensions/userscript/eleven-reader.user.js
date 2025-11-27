// ==UserScript==
// @name         Eleven Reader - Selection Speaker (Streaming)
// @namespace    https://github.com/user/elevenlabs-reader-cli
// @version      2.8.0
// @description  Floating speaker button with gapless streaming audio via ElevenLabs Reader
// @author       You
// @match        *://*/*
// @grant        GM_xmlhttpRequest
// @grant        GM_addStyle
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  const API_BASE = "http://127.0.0.1:8011";
  const API_STREAM = `${API_BASE}/api/stream`;
  const BUTTON_ID = "eleven-reader-speak-btn";
  const TOAST_ID = "eleven-reader-toast";
  
  // Flow control settings
  const MAX_PENDING_CHUNKS = 8;      // Max chunks to buffer
  const PRELOAD_SECONDS = 5;         // Seconds before end to preload next batch

  // Speaker icon SVG
  const SPEAKER_SVG = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
      <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
    </svg>
  `;

  // Inject styles
  GM_addStyle(`
    #${BUTTON_ID} {
      position: absolute;
      z-index: 2147483647;
      width: 36px;
      height: 36px;
      border-radius: 50%;
      border: none;
      background: rgba(30, 30, 30, 0.85);
      color: #fff;
      cursor: pointer;
      display: none;
      align-items: center;
      justify-content: center;
      box-shadow: 0 4px 16px rgba(0,0,0,0.3);
      backdrop-filter: blur(8px);
      transition: transform 0.15s ease, background 0.15s ease, opacity 0.2s ease;
      opacity: 0;
      pointer-events: none;
    }
    #${BUTTON_ID}.visible {
      display: flex;
      opacity: 1;
      pointer-events: auto;
    }
    #${BUTTON_ID}:hover {
      background: rgba(80, 80, 80, 0.95);
      transform: scale(1.1);
    }
    #${BUTTON_ID}:active {
      transform: scale(0.95);
    }
    #${BUTTON_ID}.loading {
      pointer-events: none;
      animation: eleven-pulse 1s infinite;
    }
    #${BUTTON_ID}.loading svg {
      opacity: 0.5;
    }
    #${BUTTON_ID}.streaming {
      background: rgba(40, 160, 70, 0.9);
      animation: eleven-stream-pulse 0.8s infinite;
    }
    @keyframes eleven-pulse {
      0%, 100% { box-shadow: 0 4px 16px rgba(0,0,0,0.3); }
      50% { box-shadow: 0 4px 24px rgba(100,200,255,0.5); }
    }
    @keyframes eleven-stream-pulse {
      0%, 100% { box-shadow: 0 4px 16px rgba(40,160,70,0.4); }
      50% { box-shadow: 0 4px 24px rgba(40,160,70,0.8); }
    }

    #${TOAST_ID} {
      position: fixed;
      bottom: 24px;
      right: 24px;
      max-width: 300px;
      padding: 12px 16px;
      border-radius: 10px;
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 14px;
      background: rgba(30, 30, 30, 0.92);
      color: #fff;
      box-shadow: 0 8px 32px rgba(0,0,0,0.3);
      backdrop-filter: blur(8px);
      z-index: 2147483647;
      opacity: 0;
      transform: translateY(12px);
      transition: opacity 0.25s ease, transform 0.25s ease;
      pointer-events: none;
    }
    #${TOAST_ID}.visible {
      opacity: 1;
      transform: translateY(0);
    }
    #${TOAST_ID}.error {
      background: rgba(200, 50, 50, 0.92);
    }
    #${TOAST_ID}.success {
      background: rgba(40, 160, 70, 0.92);
    }
    #${TOAST_ID}.streaming {
      background: rgba(70, 130, 180, 0.92);
    }
  `);

  let button = null;
  let toast = null;
  let hideTimeout = null;
  let toastTimeout = null;
  let currentRequest = null;
  
  // Streaming state
  let pendingChunks = [];       // Chunks waiting to be played
  let pendingBytes = 0;
  let currentAudio = null;
  let currentBlobUrl = null;
  let nextAudio = null;         // Preloaded next audio
  let nextBlobUrl = null;
  let streamComplete = false;
  let isPlaying = false;
  let totalChunksReceived = 0;
  let totalChunksPlayed = 0;
  let totalBytesReceived = 0;
  let preloadTimer = null;
  let hasPreloaded = false;

  const createButton = () => {
    if (button) return button;
    button = document.createElement("button");
    button.id = BUTTON_ID;
    button.innerHTML = SPEAKER_SVG;
    button.title = "Read with Eleven Reader";
    button.addEventListener("click", handleClick);
    document.body.appendChild(button);
    return button;
  };

  const createToast = () => {
    if (toast) return toast;
    toast = document.createElement("div");
    toast.id = TOAST_ID;
    document.body.appendChild(toast);
    return toast;
  };

  const showToast = (message, variant = "info", duration = 3500) => {
    const t = createToast();
    t.textContent = message;
    t.className = variant === "error" ? "error" : variant === "success" ? "success" : variant === "streaming" ? "streaming" : "";
    void t.offsetWidth;
    t.classList.add("visible");

    if (toastTimeout) clearTimeout(toastTimeout);
    if (duration > 0) {
      toastTimeout = setTimeout(() => {
        t.classList.remove("visible");
      }, duration);
    }
  };

  const hideToast = () => {
    if (toast) toast.classList.remove("visible");
  };

  const showButton = (x, y) => {
    const btn = createButton();
    btn.style.left = `${x}px`;
    btn.style.top = `${y}px`;
    btn.classList.remove("loading", "streaming");
    btn.classList.add("visible");
    if (hideTimeout) clearTimeout(hideTimeout);
  };

  const hideButton = () => {
    if (button) button.classList.remove("visible", "loading", "streaming");
  };

  const getSelectedText = () => {
    const sel = window.getSelection();
    return sel ? sel.toString().trim() : "";
  };

  const resetState = () => {
    if (currentRequest) {
      try { currentRequest.abort(); } catch (_) {}
      currentRequest = null;
    }
    if (preloadTimer) {
      clearInterval(preloadTimer);
      preloadTimer = null;
    }
    if (currentAudio) {
      try { currentAudio.pause(); } catch (_) {}
      currentAudio = null;
    }
    if (nextAudio) {
      try { nextAudio.pause(); } catch (_) {}
      nextAudio = null;
    }
    if (currentBlobUrl) {
      URL.revokeObjectURL(currentBlobUrl);
      currentBlobUrl = null;
    }
    if (nextBlobUrl) {
      URL.revokeObjectURL(nextBlobUrl);
      nextBlobUrl = null;
    }
    pendingChunks = [];
    pendingBytes = 0;
    streamComplete = false;
    isPlaying = false;
    totalChunksReceived = 0;
    totalChunksPlayed = 0;
    totalBytesReceived = 0;
    hasPreloaded = false;
  };

  const base64ToBytes = (base64) => {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  };

  // Create audio element from pending chunks without clearing them yet
  const createAudioFromPending = () => {
    if (pendingChunks.length === 0) return null;
    
    const combined = new Uint8Array(pendingBytes);
    let offset = 0;
    for (const chunk of pendingChunks) {
      combined.set(chunk, offset);
      offset += chunk.length;
    }
    
    const blob = new Blob([combined], { type: "audio/mpeg" });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio._blobUrl = url;
    audio._chunkCount = pendingChunks.length;
    
    return { audio, url, chunkCount: pendingChunks.length };
  };

  // Clear pending chunks (call after we've used them)
  const clearPending = () => {
    const count = pendingChunks.length;
    pendingChunks = [];
    pendingBytes = 0;
    return count;
  };

  // Preload next batch of audio
  const preloadNext = () => {
    if (nextAudio || pendingChunks.length === 0) return;
    
    const result = createAudioFromPending();
    if (!result) return;
    
    nextAudio = result.audio;
    nextBlobUrl = result.url;
    hasPreloaded = true;
    
    // Preload the audio
    nextAudio.preload = "auto";
    nextAudio.load();
    
    // Clear pending since we've captured them
    const count = clearPending();
    console.log(`Eleven Reader: preloaded ${count} chunks`);
  };

  // Check if we should preload (called periodically during playback)
  const checkPreload = () => {
    if (!currentAudio || nextAudio || pendingChunks.length === 0) return;
    
    const remaining = currentAudio.duration - currentAudio.currentTime;
    
    // Preload when PRELOAD_SECONDS remain, or if duration is short
    if (remaining <= PRELOAD_SECONDS || currentAudio.duration <= PRELOAD_SECONDS) {
      preloadNext();
    }
  };

  // Start preload monitoring
  const startPreloadMonitor = () => {
    if (preloadTimer) return;
    preloadTimer = setInterval(checkPreload, 500);
  };

  const stopPreloadMonitor = () => {
    if (preloadTimer) {
      clearInterval(preloadTimer);
      preloadTimer = null;
    }
  };

  // Finish playback
  const finishPlayback = () => {
    stopPreloadMonitor();
    button.classList.remove("streaming", "loading");
    const mb = (totalBytesReceived / 1024 / 1024).toFixed(1);
    showToast(`Finished · ${totalChunksPlayed} chunks (${mb}MB)`, "success", 3000);
    
    if (currentBlobUrl) {
      URL.revokeObjectURL(currentBlobUrl);
      currentBlobUrl = null;
    }
    if (nextBlobUrl) {
      URL.revokeObjectURL(nextBlobUrl);
      nextBlobUrl = null;
    }
    isPlaying = false;
  };

  // Play audio (current or switch to preloaded)
  const playAudio = (audio, blobUrl, chunkCount) => {
    // Clean up previous
    if (currentBlobUrl && currentBlobUrl !== blobUrl) {
      URL.revokeObjectURL(currentBlobUrl);
    }
    
    currentAudio = audio;
    currentBlobUrl = blobUrl;
    isPlaying = true;
    totalChunksPlayed += chunkCount;

    audio.addEventListener("ended", () => {
      // If we have preloaded audio, play it immediately
      if (nextAudio) {
        const na = nextAudio;
        const nb = nextBlobUrl;
        const nc = na._chunkCount || 0;
        nextAudio = null;
        nextBlobUrl = null;
        hasPreloaded = false;
        
        playAudio(na, nb, nc);
        return;
      }
      
      // No preloaded audio - check if we have pending chunks
      if (pendingChunks.length > 0) {
        const result = createAudioFromPending();
        if (result) {
          const count = clearPending();
          playAudio(result.audio, result.url, count);
          return;
        }
      }
      
      // Nothing more to play
      if (streamComplete) {
        finishPlayback();
      } else {
        // Stream still going, wait for more chunks
        isPlaying = false;
        stopPreloadMonitor();
      }
    }, { once: true });

    audio.addEventListener("error", (e) => {
      console.error("Eleven Reader: audio error", e);
      URL.revokeObjectURL(blobUrl);
      
      // Try to continue
      if (nextAudio) {
        const na = nextAudio;
        const nb = nextBlobUrl;
        const nc = na._chunkCount || 0;
        nextAudio = null;
        nextBlobUrl = null;
        playAudio(na, nb, nc);
      } else if (pendingChunks.length > 0) {
        const result = createAudioFromPending();
        if (result) {
          const count = clearPending();
          playAudio(result.audio, result.url, count);
        }
      } else {
        isPlaying = false;
      }
    }, { once: true });

    // Update UI
    button.classList.remove("loading");
    button.classList.add("streaming");
    showToast(`Playing...`, "streaming", 0);

    // Start preload monitoring
    startPreloadMonitor();

    audio.play().catch((err) => {
      console.error("Eleven Reader: play failed", err);
      isPlaying = false;
      showToast("Playback failed", "error");
    });
  };

  // Start playback with pending chunks
  const startPlayback = () => {
    if (isPlaying || pendingChunks.length === 0) return;
    
    const result = createAudioFromPending();
    if (!result) return;
    
    const count = clearPending();
    playAudio(result.audio, result.url, count);
  };

  // Add a new chunk
  const addChunk = (audioBytes) => {
    totalChunksReceived++;
    totalBytesReceived += audioBytes.length;
    
    // Add to pending
    pendingChunks.push(audioBytes);
    pendingBytes += audioBytes.length;
    
    console.log(`Eleven Reader: chunk ${totalChunksReceived} (${audioBytes.length} bytes), pending: ${pendingChunks.length}`);
    
    // If not playing, start playback
    if (!isPlaying) {
      startPlayback();
    }
    // If playing and we have enough pending, preload might happen via timer
    // But also check immediately if we have a lot buffered
    else if (pendingChunks.length >= MAX_PENDING_CHUNKS && !nextAudio) {
      preloadNext();
    }
  };

  // Parse SSE events from text
  const parseSSEEvents = (text, lastParsedIndex) => {
    const events = [];
    const newText = text.substring(lastParsedIndex);
    const lines = newText.split("\n");
    
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const data = JSON.parse(line.slice(6));
          events.push(data);
        } catch (_) {}
      }
    }
    
    return events;
  };

  // Calculate button position within viewport
  const calculateButtonPosition = () => {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return null;

    const range = sel.getRangeAt(0);
    const rects = range.getClientRects();
    
    if (rects.length === 0) return null;

    const viewportHeight = window.innerHeight;
    const viewportWidth = window.innerWidth;
    const buttonSize = 36;
    const padding = 8;

    let targetRect = null;
    let lastVisibleRect = null;
    let firstVisibleRect = null;

    for (const rect of rects) {
      const isPartiallyVisible = rect.bottom > 0 && rect.top < viewportHeight &&
                                  rect.right > 0 && rect.left < viewportWidth;
      
      if (isPartiallyVisible) {
        if (!firstVisibleRect) firstVisibleRect = rect;
        lastVisibleRect = rect;
      }
    }

    targetRect = lastVisibleRect || firstVisibleRect || range.getBoundingClientRect();

    let x = targetRect.right + padding;
    let y = targetRect.top + (targetRect.height / 2) - (buttonSize / 2);

    if (x + buttonSize > viewportWidth - padding) {
      x = targetRect.left - buttonSize - padding;
    }
    if (x < padding) {
      x = viewportWidth - buttonSize - padding;
    }
    if (y < padding) {
      y = padding;
    }
    if (y + buttonSize > viewportHeight - padding) {
      y = viewportHeight - buttonSize - padding;
    }

    return {
      x: x + window.scrollX,
      y: y + window.scrollY
    };
  };

  // Streaming request using native fetch with ReadableStream for true streaming
  const handleStreamingRequest = (text) => {
    return new Promise(async (resolve, reject) => {
      let seenChunks = new Set();
      let buffer = "";

      const processLine = (line) => {
        if (!line.startsWith("data: ")) return;
        
        try {
          const data = JSON.parse(line.slice(6));
          
          if (data.type === "chunk" && data.audio) {
            const chunkKey = data.chunk_num || totalChunksReceived + 1;
            if (!seenChunks.has(chunkKey)) {
              seenChunks.add(chunkKey);
              const bytes = base64ToBytes(data.audio);
              addChunk(bytes);
            }
          } else if (data.type === "status") {
            console.log("Eleven Reader:", data.message);
            if (!isPlaying) {
              if (data.message === "Document ready") {
                showToast("Generating audio...", "streaming", 0);
              } else if (data.message && data.message.includes("created")) {
                showToast("Document created...", "streaming", 0);
              }
            }
          } else if (data.type === "done") {
            streamComplete = true;
            console.log("Eleven Reader: stream complete,", totalChunksReceived, "chunks,", totalBytesReceived, "bytes");
            
            if (!isPlaying && pendingChunks.length > 0) {
              startPlayback();
            } else if (!isPlaying && pendingChunks.length === 0) {
              finishPlayback();
            }
          } else if (data.type === "error") {
            throw new Error(data.message);
          }
        } catch (e) {
          // Incomplete JSON, will retry with more data
          if (e.message && !e.message.includes("JSON")) {
            throw e;
          }
        }
      };

      try {
        const response = await fetch(API_STREAM, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        // Store abort function
        currentRequest = {
          abort: () => {
            reader.cancel();
          }
        };

        while (true) {
          const { done, value } = await reader.read();
          
          if (done) {
            // Process any remaining buffer
            if (buffer.trim()) {
              const lines = buffer.split("\n");
              for (const line of lines) {
                if (line.trim()) processLine(line);
              }
            }
            break;
          }

          // Decode chunk and add to buffer
          buffer += decoder.decode(value, { stream: true });
          
          // Process complete lines
          const lines = buffer.split("\n");
          buffer = lines.pop() || ""; // Keep incomplete line in buffer
          
          for (const line of lines) {
            if (line.trim()) {
              processLine(line);
            }
          }
        }

        streamComplete = true;
        
        if (!isPlaying && pendingChunks.length > 0) {
          startPlayback();
        }
        
        resolve({ chunks: totalChunksReceived });

      } catch (err) {
        button.classList.remove("loading", "streaming");
        console.error("Eleven Reader: streaming error", err);
        reject(err);
      }
    });
  };

  const handleClick = async (e) => {
    e.preventDefault();
    e.stopPropagation();

    const text = getSelectedText();
    if (!text) {
      showToast("No text selected", "error");
      hideButton();
      return;
    }

    resetState();
    button.classList.add("loading");
    
    const wordCount = text.split(/\s+/).length;
    showToast(`Connecting... (${wordCount.toLocaleString()} words)`, "info", 0);

    try {
      await handleStreamingRequest(text);
    } catch (err) {
      console.error("Eleven Reader: streaming failed", err);
      
      if (!isPlaying && pendingChunks.length === 0 && totalChunksReceived === 0) {
        showToast(`Error: ${err.message}`, "error");
        button.classList.remove("loading", "streaming");
      }
    }
  };

  // Track selection changes
  document.addEventListener("mouseup", (e) => {
    if (e.target.id === BUTTON_ID || e.target.closest(`#${BUTTON_ID}`)) return;

    setTimeout(() => {
      const text = getSelectedText();
      if (text && text.length > 0) {
        const pos = calculateButtonPosition();
        if (pos) {
          showButton(pos.x, pos.y);
        }
      } else {
        hideButton();
      }
    }, 10);
  });

  document.addEventListener("mousedown", (e) => {
    if (e.target.id !== BUTTON_ID && !e.target.closest(`#${BUTTON_ID}`)) {
      hideTimeout = setTimeout(hideButton, 150);
    }
  });

  document.addEventListener("scroll", hideButton, { passive: true });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      hideButton();
      hideToast();
      resetState();
    }
  });

  console.log("Eleven Reader userscript loaded (v2.9.0 - true streaming with fetch ReadableStream)");
})();
