const fs = require('fs');

// 1. Patch ids.js
const idsPath = '/app/dist/core/utils/ids.js';
let idsJs = fs.readFileSync(idsPath, 'utf8');
const newParse = `function parseMessageIdSerialized(messageId, soft = false) {
    if (!messageId) return { id: "", fromMe: false, remoteJid: "", participant: undefined };
    if (typeof messageId !== "string") {
        if (messageId._serialized) messageId = messageId._serialized;
        else if (messageId.id) return { id: messageId.id, fromMe: Boolean(messageId.fromMe), remoteJid: (0, jids_1.toJID)(messageId.remote?._serialized || messageId.remote || ""), participant: undefined };
        else messageId = String(messageId);
    }
    if (!messageId.includes("_")) return { id: messageId, fromMe: false, remoteJid: "", participant: undefined };
    const parts = messageId.split("_");
    if (parts.length != 3 && parts.length != 4) return { id: messageId, fromMe: false, remoteJid: "", participant: undefined };
    const fromMe = parts[0] == "true";
    const chatId = parts[1];
    const remoteJid = (0, jids_1.toJID)(chatId);
    const id = parts[2];
    const participant = parts[3] ? (0, jids_1.toJID)(parts[3]) : undefined;
    return { fromMe, id, remoteJid, participant };
}`;
idsJs = idsJs.replace(/function parseMessageIdSerialized\([\s\S]*?^\}/m, newParse);
fs.writeFileSync(idsPath, idsJs);

// 2. Patch session.webjs.core.js
const webjsPath = '/app/dist/core/engines/webjs/session.webjs.core.js';
let webjs = fs.readFileSync(webjsPath, 'utf8');
webjs = webjs.replace(
    /toWAMessage\(message\)\s*\{[\s\S]*?const replyTo = this\.extractReplyTo\(message\);[\s\S]*?const source = this\.getMessageSource\(message\.id\.id\);[\s\S]*?const key = \(0, ids_1\.parseMessageIdSerialized\)\(message\.id\._serialized\);/m,
    `toWAMessage(message) {
        var _a;
        const msgId = typeof message.id === "string" ? message.id : (message.id?._serialized || message.id?.id || "msg_" + Date.now());
        const replyTo = this.extractReplyTo(message);
        const source = this.getMessageSource(message.id?.id || msgId);
        const key = (0, ids_1.parseMessageIdSerialized)(msgId, true);`
);
webjs = webjs.replace(/id: message\.id\._serialized,/g, "id: (typeof message.id === 'string' ? message.id : (message.id?._serialized || message.id?.id || 'msg_' + Date.now())),");
fs.writeFileSync(webjsPath, webjs);

console.log("SUCCESSFULLY_PATCHED_WAHA");
