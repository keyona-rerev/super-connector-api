/**
 * ContactRepair.gs
 * 
 * Step 1: repairContactIds()
 *   - Assigns unique IDs to all 4,400 contacts in the Sheet
 *   - Writes new IDs back to column A
 *   - Safe to run multiple times (skips rows that already have unique IDs)
 *
 * Step 2: pushAllContactsToRailway()
 *   - Pushes all contacts with new IDs to Railway in batches of 100
 *   - Vectorizes each contact via Voyage AI on arrival
 *   - This replaces the broken bulk that only stored one record
 *
 * Run Step 1 first, confirm in logs, then run Step 2.
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

  if (idCol < 0) {
    Logger.log('ERROR: Contact ID column not found');
    return;
  }

  // Collect all existing IDs to detect duplicates
  var existingIds = {};
  data.slice(1).forEach(function(row) {
    var id = String(row[idCol] || '');
    existingIds[id] = (existingIds[id] || 0) + 1;
  });

  var duplicates = Object.keys(existingIds).filter(function(id) {
    return existingIds[id] > 1;
  });

  Logger.log('Duplicate IDs found: ' + duplicates.length);
  Logger.log('Most common duplicate: ' + duplicates[0] + ' (' + existingIds[duplicates[0]] + ' rows)');

  // Assign new unique IDs to every row that has a duplicate ID
  // We use a counter-based ID: C + timestamp_base + row_index
  var seenIds = {};
  var repaired = 0;
  var updates  = []; // {rowIndex, newId}

  for (var i = 1; i < data.length; i++) {
    var currentId = String(data[i][idCol] || '');

    // Skip rows with no name (blank rows)
    var nameCol = headers.indexOf('Full Name');
    if (nameCol >= 0 && !data[i][nameCol]) continue;

    // If this ID has already been used, it's a duplicate — generate new one
    if (seenIds[currentId]) {
      var newId = 'C' + (1773968000000 + i); // deterministic, unique per row
      updates.push({ rowIndex: i + 1, newId: newId }); // +1 for 1-based sheet rows
      seenIds[newId] = true;
      repaired++;
    } else {
      seenIds[currentId] = true;
    }
  }

  Logger.log('Rows needing new IDs: ' + repaired);

  // Write all updates in one batch
  updates.forEach(function(u) {
    sheet.getRange(u.rowIndex, idCol + 1).setValue(u.newId);
  });

  Logger.log('Done. ' + repaired + ' Contact IDs repaired.');
  Logger.log('Run pushAllContactsToRailway() next.');
}

// ── STEP 2: Push all contacts to Railway ─────────────────────────────────────
function pushAllContactsToRailway() {
  var sheet   = SpreadsheetApp.openById(REPAIR_SHEET_ID).getSheetByName('Contacts');
  var data    = sheet.getDataRange().getValues();
  var headers = data[0];

  var col = {
    contact_id:           headers.indexOf('Contact ID'),
    full_name:            headers.indexOf('Full Name'),
    title_role:           headers.indexOf('Title / Role'),
    organization:         headers.indexOf('Organization'),
    email:                headers.indexOf('Email'),
    how_we_met:           headers.indexOf('How We Met'),
    venture:              headers.indexOf('Venture'),
    what_building:        headers.indexOf("What They're Building"),
    what_need:            headers.indexOf('What They Need'),
    what_offer:           headers.indexOf('What They Offer'),
    relationship_health:  headers.indexOf('Relationship Health'),
    activation_potential: headers.indexOf('Activation Potential'),
    notes:                headers.indexOf('Notes'),
  };

  // Build contact list — skip blank rows
  var contacts = data.slice(1)
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

  Logger.log('Total contacts to push: ' + contacts.length);

  var totalSuccess = 0;
  var totalSkipped = 0;
  var totalErrors  = 0;
  var key = _getRailwayKey();

  for (var i = 0; i < contacts.length; i += BATCH_SIZE) {
    var batch    = contacts.slice(i, i + BATCH_SIZE);
    var batchNum = Math.floor(i / BATCH_SIZE) + 1;

    try {
      var res = UrlFetchApp.fetch(RAILWAY_API_BASE + '/contact/bulk', {
        method: 'post',
        muteHttpExceptions: true,
        headers: { 'Content-Type': 'application/json', 'X-API-Key': key },
        payload: JSON.stringify({ contacts: batch })
      });

      var result = JSON.parse(res.getContentText());
      totalSuccess += result.success  || 0;
      totalSkipped += result.skipped  || 0;
      totalErrors  += (result.errors  || []).length;

      Logger.log('Batch ' + batchNum + ': ' + (result.success || 0) + ' ok, ' + (result.skipped || 0) + ' skipped, ' + (result.errors || []).length + ' errors');
    } catch (e) {
      Logger.log('Batch ' + batchNum + ' FAILED: ' + e.message);
      totalErrors++;
    }

    Utilities.sleep(300);
  }

  Logger.log('=== DONE ===');
  Logger.log('Success: ' + totalSuccess + ' | Skipped: ' + totalSkipped + ' | Errors: ' + totalErrors);
}

// ── OPTIONAL: Quick ID audit ──────────────────────────────────────────────────
function auditContactIds() {
  var sheet   = SpreadsheetApp.openById(REPAIR_SHEET_ID).getSheetByName('Contacts');
  var data    = sheet.getDataRange().getValues();
  var headers = data[0];
  var idCol   = headers.indexOf('Contact ID');

  var counts = {};
  var blank  = 0;
  data.slice(1).forEach(function(row) {
    var id = String(row[idCol] || '');
    if (!id) { blank++; return; }
    counts[id] = (counts[id] || 0) + 1;
  });

  var unique     = Object.keys(counts).filter(function(id) { return counts[id] === 1; }).length;
  var duplicated = Object.keys(counts).filter(function(id) { return counts[id] > 1; }).length;
  var totalRows  = data.length - 1;

  Logger.log('Total rows: '      + totalRows);
  Logger.log('Blank IDs: '       + blank);
  Logger.log('Unique IDs: '      + unique);
  Logger.log('Duplicate IDs: '   + duplicated);
  Logger.log('Rows needing fix: ' + (totalRows - unique - blank));
}
