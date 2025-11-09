/**
 * Hybrid tracking via Google Apps Script + Google Sheets.
 * 1) Crea un Google Sheet e prendi l'ID. Crea i fogli: "opens" (ts,cid,to,ua,ip) e "unsubs" (ts,email).
 * 2) In Apps Script incolla questo codice e sostituisci SHEET_ID.
 * 3) Deploy -> Web app -> Access: Anyone.
 * 4) Usa la Web App URL in campaign_config.yaml (tracking_base_url/unsubscribe_base_url).
 */

const SHEET_ID = "INSERISCI_GOOGLE_SHEET_ID";

function doGet(e) {
  const mode = (e.parameter.mode || "pixel").toLowerCase();
  if (mode === "unsubscribe") return handleUnsubscribe(e);
  return handlePixel(e);
}

function handlePixel(e) {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const sh = getOrCreateSheet(ss, "opens", ["ts","cid","to","ua","ip"]);
  const ts = new Date();
  const cid = e.parameter.cid || "";
  const to = e.parameter.to || "";
  const ua = e.parameter.ua || "";
  const ip = e.parameter.ip || "";
  sh.appendRow([ts, cid, to, ua, ip]);

  const bytes = Utilities.base64Decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/URn3jsAAAAASUVORK5CYII="
  );
  return ContentService.createBinaryOutput(bytes)
    .setMimeType(ContentService.MimeType.PNG);
}

function handleUnsubscribe(e) {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const sh = getOrCreateSheet(ss, "unsubs", ["ts","email"]);
  const ts = new Date();
  const email = e.parameter.email || "";
  sh.appendRow([ts, email]);
  return ContentService.createTextOutput("Disiscrizione registrata.")
    .setMimeType(ContentService.MimeType.TEXT);
}

function getOrCreateSheet(ss, name, headers) {
  let sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name);
    sh.appendRow(headers);
  }
  return sh;
}
