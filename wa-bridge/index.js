/**
 * Railway entry point for the WhatsApp bridge worker service.
 * Root directory for this Railway service: wa-bridge/
 * Loads the bridge from the parent repo directory.
 */

// Session stored on Railway volume (/data mounted in Railway dashboard)
process.env.WA_SESSION_DIR = process.env.WA_SESSION_DIR || "/data/whatsapp-session";

// Load the bridge
require("../truman/integrations/whatsapp_bridge.js");
