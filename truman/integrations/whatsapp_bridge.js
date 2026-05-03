/**
 * whatsapp_bridge.js — Truman's WhatsApp auto-send bridge (Phase 15B)
 *
 * Registers as a WhatsApp linked device (like WhatsApp Desktop).
 * First run: prints QR in terminal — scan once, done forever.
 * Session persists in truman/data/wa_session/ across restarts.
 *
 * Endpoints:
 *   GET  /status      → {ok: true, state: "CONNECTED"|"QR_PENDING"|"DOWN"}
 *   POST /send        → {to: "12345678901", text: "..."}  (E.164, no +)
 *
 * Start: node truman/integrations/whatsapp_bridge.js
 * Port:  3099 (localhost only — never exposed externally)
 */

const { Client, LocalAuth } = require("whatsapp-web.js");
const qrcode  = require("qrcode-terminal");
const express = require("express");
const path    = require("path");

const PORT        = 3099;
const DATA_DIR    = path.join(__dirname, "../../data/wa_session");
const READY_TIMEOUT = 60_000; // ms to wait for READY before marking DOWN

let _state  = "QR_PENDING";   // QR_PENDING | CONNECTED | DOWN
let _client = null;

// ── Init WhatsApp client ──────────────────────────────────────────────────────
function startClient() {
  _client = new Client({
    authStrategy: new LocalAuth({ dataPath: DATA_DIR }),
    puppeteer: {
      headless: true,
      args: ["--no-sandbox", "--disable-setuid-sandbox"],
    },
  });

  _client.on("qr", (qr) => {
    _state = "QR_PENDING";
    console.log("[WA Bridge] Scan this QR code in WhatsApp → Linked Devices:");
    qrcode.generate(qr, { small: true });
  });

  _client.on("ready", () => {
    _state = "CONNECTED";
    console.log("[WA Bridge] ✅ WhatsApp connected. Bridge ready on port", PORT);
  });

  // ── Incoming messages → forward to Railway for triage ──────────────────────
  _client.on("message", async (msg) => {
    try {
      // Skip messages sent by us, broadcasts, status updates
      if (msg.fromMe) return;
      if (msg.from === "status@broadcast") return;

      const body    = msg.body || "";
      const from    = msg.from;       // e.g. "12223334444@c.us"
      const contact = await msg.getContact();
      const name    = contact.pushname || contact.name || from.replace("@c.us", "");
      const isGroup = msg.from.endsWith("@g.us");

      if (!body.trim()) return;

      console.log(`[WA Bridge] Incoming from ${name}: ${body.slice(0, 80)}`);

      // POST to Railway (or local Truman) — RAILWAY_URL env var, fallback localhost
      const railwayUrl = process.env.RAILWAY_URL || "http://127.0.0.1:5000";
      const res = await fetch(`${railwayUrl}/api/boss_message`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          from:   name,
          text:   body,
          source: "whatsapp",
          extra:  { phone: from.replace("@c.us", ""), is_group: isGroup },
        }),
      });
      if (!res.ok) {
        console.warn(`[WA Bridge] Forward failed: ${res.status}`);
      }
    } catch (e) {
      console.error("[WA Bridge] Incoming handler error:", e.message);
    }
  });

  _client.on("auth_failure", (msg) => {
    _state = "DOWN";
    console.error("[WA Bridge] Auth failure:", msg);
  });

  _client.on("disconnected", (reason) => {
    _state = "DOWN";
    console.warn("[WA Bridge] Disconnected:", reason, "— will attempt reconnect in 30s");
    setTimeout(() => {
      _client.initialize().catch(console.error);
    }, 30_000);
  });

  _client.initialize().catch((e) => {
    _state = "DOWN";
    console.error("[WA Bridge] Init error:", e.message);
  });
}

// ── HTTP server ───────────────────────────────────────────────────────────────
const app = express();
app.use(express.json());

app.get("/status", (_req, res) => {
  res.json({ ok: _state === "CONNECTED", state: _state });
});

app.post("/send", async (req, res) => {
  const { to, text } = req.body || {};
  if (!to || !text) {
    return res.status(400).json({ ok: false, error: "Missing to or text" });
  }
  if (_state !== "CONNECTED") {
    return res.status(503).json({ ok: false, error: `Bridge state: ${_state}` });
  }
  try {
    // WhatsApp requires number@c.us format
    const chatId = to.replace(/\D/g, "") + "@c.us";
    await _client.sendMessage(chatId, text);
    console.log(`[WA Bridge] Sent to ${to}: ${text.slice(0, 60)}...`);
    res.json({ ok: true });
  } catch (e) {
    console.error("[WA Bridge] Send error:", e.message);
    res.status(500).json({ ok: false, error: e.message });
  }
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`[WA Bridge] HTTP server listening on localhost:${PORT}`);
  startClient();
});

process.on("SIGTERM", () => {
  console.log("[WA Bridge] SIGTERM received — shutting down.");
  if (_client) _client.destroy().catch(() => {});
  process.exit(0);
});
