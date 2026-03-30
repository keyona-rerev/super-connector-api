/**
 * ContactRepair.gs
 * 
 * Step 1: repairContactIds()
 * Step 2: pushAllContactsToRailway()  — or use pushContactsFromRow(4301) to resume
 * Step 3: auditContactIds()           — verify everything is clean
 * Step 4: scoreRelationshipHealth()   — populate Relationship Health + Activation Potential
 */

var REPAIR_SHEET_ID  = '1WO6YK2alMx7Wu49Vpm1NZBN5fdquNUmCvgpIhjNK10g';
var RAILWAY_API_BASE = 'https://super-connector-api-production.up.railway.app';
var BATCH_SIZE       = 100;

function _getRailwayKey() {
  var key = PropertiesService.getScriptProperties().getProperty('SC_API_KEY');
  if (!key) throw new Error('SC_API_KEY not set in Script Properties');
  return key;
}

// ── STEP 1: Repair Contact IDs ────────────────────────────────────────────────
function repairContactIds() {
  var sheet = SpreadsheetApp.openById(REPAIR_SHEET_ID).getSheetByName('Contacts');
  var data  = sheet.getDataRange().getValues();
  var headers = data[0];
  var idCol   = headers.indexOf('Contact ID');

  if (idCol < 0) { Logger.log('ERROR: Contact ID column not found'); return; }

  var existingIds = {};
  data.slice(1).forEach(function(row) {
    var id = String(row[idCol] || '');
    existingIds[id] = (existingIds[id] || 0) + 1;
  });

  var duplicates = Object.keys(existingIds).filter(function(id) { return existingIds[id] > 1; });
  Logger.log('Duplicate IDs found: ' + duplicates.length);

  var seenIds = {};
  var repaired = 0;
  var updates  = [];

  for (var i = 1; i < data.length; i++) {
    var currentId = String(data[i][idCol] || '');
    var nameCol = headers.indexOf('Full Name');
    if (nameCol >= 0 && !data[i][nameCol]) continue;
    if (seenIds[currentId]) {
      var newId = 'C' + (1773968000000 + i);
      updates.push({ rowIndex: i + 1, newId: newId });
      seenIds[newId] = true;
      repaired++;
    } else {
      seenIds[currentId] = true;
    }
  }

  updates.forEach(function(u) {
    sheet.getRange(u.rowIndex, idCol + 1).setValue(u.newId);
  });

  Logger.log('Done. ' + repaired + ' Contact IDs repaired.');
}

// ── STEP 2a: Push ALL contacts ────────────────────────────────────────────────
function pushAllContactsToRailway() {
  pushContactsFromRow(1);
}

// ── STEP 2b: Resume from a specific data row (use after timeout) ──────────────
// Pass the contact number you want to start from (e.g. 4301 to push the last 101)
function pushContactsFromRow(startContactIndex) {
  var sheet   = SpreadsheetApp.openById(REPAIR_SHEET_ID).getSheetByName('Contacts');
  var data    = sheet.getDataRange().getValues();
  var headers = data[0];

  var col = {
    contact_id:           headers.indexOf('Contact ID'),
    full_name:            headers.indexOf('Full Name'),
    title_role:           headers.indexOf('Title / Role'),
    organization:         headers.indexOf('Organization'),
    how_we_met:           headers.indexOf('How We Met'),
    venture:              headers.indexOf('Venture'),
    what_building:        headers.indexOf("What They're Building"),
    what_need:            headers.indexOf('What They Need'),
    what_offer:           headers.indexOf('What They Offer'),
    relationship_health:  headers.indexOf('Relationship Health'),
    activation_potential: headers.indexOf('Activation Potential'),
    notes:                headers.indexOf('Notes'),
  };

  var allContacts = data.slice(1)
    .filter(function(r) { return r[col.full_name]; })
    .map(function(r) {
      return {
        contact_id:           String(r[col.contact_id]           || ''),
        full_name:            String(r[col.full_name]            || ''),
        title_role:           String(r[col.title_role]           || ''),
        organization:         String(r[col.organization]         || ''),
        how_we_met:           String(r[col.how_we_met]           || ''),
        venture:              String(r[col.venture]              || ''),
        what_building:        String(r[col.what_building]        || ''),
        what_need:            String(r[col.what_need]            || ''),
        what_offer:           String(r[col.what_offer]           || ''),
        relationship_health:  String(r[col.relationship_health]  || ''),
        activation_potential: String(r[col.activation_potential] || ''),
        notes:                String(r[col.notes]                || ''),
      };
    });

  // startContactIndex is 1-based (1 = first contact)
  var start = (startContactIndex || 1) - 1;
  var contacts = allContacts.slice(start);
  Logger.log('Resuming from contact ' + (start + 1) + '. Pushing ' + contacts.length + ' contacts.');

  var totalSuccess = 0, totalSkipped = 0, totalErrors = 0;
  var key = _getRailwayKey();

  for (var i = 0; i < contacts.length; i += BATCH_SIZE) {
    var batch    = contacts.slice(i, i + BATCH_SIZE);
    var batchNum = Math.floor(i / BATCH_SIZE) + 1;
    try {
      var res    = UrlFetchApp.fetch(RAILWAY_API_BASE + '/contact/bulk', {
        method: 'post', muteHttpExceptions: true,
        headers: { 'Content-Type': 'application/json', 'X-API-Key': key },
        payload: JSON.stringify({ contacts: batch })
      });
      var result = JSON.parse(res.getContentText());
      totalSuccess += result.success || 0;
      totalSkipped += result.skipped || 0;
      totalErrors  += (result.errors || []).length;
      Logger.log('Batch ' + batchNum + ': ' + (result.success||0) + ' ok, ' + (result.skipped||0) + ' skipped, ' + (result.errors||[]).length + ' errors');
    } catch (e) {
      Logger.log('Batch ' + batchNum + ' FAILED: ' + e.message);
      totalErrors++;
    }
    Utilities.sleep(300);
  }

  Logger.log('=== DONE === Success: ' + totalSuccess + ' | Skipped: ' + totalSkipped + ' | Errors: ' + totalErrors);
}

// ── STEP 3: Audit IDs ─────────────────────────────────────────────────────────
function auditContactIds() {
  var sheet   = SpreadsheetApp.openById(REPAIR_SHEET_ID).getSheetByName('Contacts');
  var data    = sheet.getDataRange().getValues();
  var headers = data[0];
  var idCol   = headers.indexOf('Contact ID');

  var counts = {}, blank = 0;
  data.slice(1).forEach(function(row) {
    var id = String(row[idCol] || '');
    if (!id) { blank++; return; }
    counts[id] = (counts[id] || 0) + 1;
  });

  var unique     = Object.keys(counts).filter(function(id) { return counts[id] === 1; }).length;
  var duplicated = Object.keys(counts).filter(function(id) { return counts[id] > 1; }).length;

  Logger.log('Total rows: '       + (data.length - 1));
  Logger.log('Unique IDs: '       + unique);
  Logger.log('Duplicate IDs: '    + duplicated);
  Logger.log('Blank IDs: '        + blank);
  Logger.log(duplicated === 0 ? 'ALL CLEAN - ready for Apollo enrichment' : 'STILL HAS DUPLICATES - run repairContactIds() again');
}

// ── STEP 4: Score Relationship Health + Activation Potential ──────────────────
// Scores every contact based on available data and writes back to the sheet.
// Safe to run multiple times — only overwrites blank cells unless forceOverwrite = true.
function scoreRelationshipHealth(forceOverwrite) {
  var sheet   = SpreadsheetApp.openById(REPAIR_SHEET_ID).getSheetByName('Contacts');
  var data    = sheet.getDataRange().getValues();
  var headers = data[0];

  var col = {
    full_name:            headers.indexOf('Full Name'),
    how_we_met:           headers.indexOf('How We Met'),
    relationship_health:  headers.indexOf('Relationship Health'),
    activation_potential: headers.indexOf('Activation Potential'),
    last_contacted:       headers.indexOf('Last Contacted'),
    notes:                headers.indexOf('Notes'),
    email:                headers.indexOf('Email'),
    organization:         headers.indexOf('Organization'),
    next_action:          headers.indexOf('Next Action'),
    venture:              headers.indexOf('Venture'),
    initiative:           headers.indexOf('Initiative'),
  };

  var now        = new Date().getTime();
  var day        = 86400000;
  var scored     = 0;
  var skipped    = 0;

  // Health score updates: collect then batch write
  var healthUpdates = [];
  var activationUpdates = [];

  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    if (!row[col.full_name]) continue; // skip blank rows

    var existingHealth     = String(row[col.relationship_health]  || '').trim();
    var existingActivation = String(row[col.activation_potential] || '').trim();

    // Skip if already scored and not forcing overwrite
    if (!forceOverwrite && existingHealth && existingActivation) {
      skipped++;
      continue;
    }

    var howMet      = String(row[col.how_we_met]     || '').toLowerCase();
    var notes       = String(row[col.notes]          || '');
    var email       = String(row[col.email]          || '').trim();
    var org         = String(row[col.organization]   || '').trim();
    var nextAction  = String(row[col.next_action]    || '').trim();
    var venture     = String(row[col.venture]        || '').trim();
    var initiative  = String(row[col.initiative]     || '').trim();
    var lastContactedRaw = row[col.last_contacted];

    var lastContactedMs = 0;
    if (lastContactedRaw) {
      var d = new Date(lastContactedRaw);
      if (!isNaN(d.getTime())) lastContactedMs = d.getTime();
    }

    var daysSinceContact = lastContactedMs ? (now - lastContactedMs) / day : 9999;

    // Is the note substantive (not just the LinkedIn import stamp)?
    var substantiveNotes = notes.length > 60 &&
      !notes.match(/^LinkedIn connection since/i);

    // ── RELATIONSHIP HEALTH ──────────────────────────────────────────────────
    var health;
    if (daysSinceContact <= 30 && substantiveNotes) {
      health = 'Hot';
    } else if (daysSinceContact <= 30 || (daysSinceContact <= 90 && substantiveNotes)) {
      health = 'Warm';
    } else if (
      howMet !== 'linkedin' &&
      howMet !== '' &&
      !howMet.startsWith('linkedin')
    ) {
      // Met in person, warm intro, event, etc.
      health = 'Warm';
    } else if (daysSinceContact <= 180 || substantiveNotes) {
      health = 'Lukewarm';
    } else {
      health = 'Cold';
    }

    // ── ACTIVATION POTENTIAL ─────────────────────────────────────────────────
    var activation;
    if (initiative || venture) {
      // Tied to an initiative or venture = highest potential
      activation = 'Super Connector';
    } else if (health === 'Hot' || health === 'Warm') {
      activation = email ? 'High' : 'Medium';
    } else if (substantiveNotes || nextAction || email) {
      activation = 'Medium';
    } else {
      activation = 'Low';
    }

    // Only write if blank or forceOverwrite
    if (forceOverwrite || !existingHealth) {
      healthUpdates.push({ row: i + 1, val: health });
    }
    if (forceOverwrite || !existingActivation) {
      activationUpdates.push({ row: i + 1, val: activation });
    }
    scored++;
  }

  // Batch write health scores
  healthUpdates.forEach(function(u) {
    sheet.getRange(u.row, col.relationship_health + 1).setValue(u.val);
  });

  // Batch write activation scores
  activationUpdates.forEach(function(u) {
    sheet.getRange(u.row, col.activation_potential + 1).setValue(u.val);
  });

  Logger.log('Scored: ' + scored + ' contacts');
  Logger.log('Skipped (already scored): ' + skipped);
  Logger.log('Health updates written: ' + healthUpdates.length);
  Logger.log('Activation updates written: ' + activationUpdates.length);
  Logger.log('Done. Run pushContactsFromRow(1) to re-push with scores to Railway.');
}
