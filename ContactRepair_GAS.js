/**
 * ContactRepair.gs
 * 
 * Step 1: repairContactIds()
 * Step 2: pushAllContactsToRailway()  — or use pushContactsFromRow(N) to resume
 * Step 3: auditContactIds()           — verify everything is clean
 * Step 4: scoreRelationshipHealth()   — populate Relationship Health + Activation Potential
 * Step 5: enrichWithApollo()          — enrich high-value contacts via Apollo API
 *         enrichWithApolloFromRow(N)  — resume Apollo enrichment after timeout
 */

var REPAIR_SHEET_ID  = '1WO6YK2alMx7Wu49Vpm1NZBN5fdquNUmCvgpIhjNK10g';
var RAILWAY_API_BASE = 'https://super-connector-api-production.up.railway.app';
var BATCH_SIZE       = 100;

function _getRailwayKey() {
  var key = PropertiesService.getScriptProperties().getProperty('SC_API_KEY');
  if (!key) throw new Error('SC_API_KEY not set in Script Properties');
  return key;
}

function _getApolloKey() {
  var key = PropertiesService.getScriptProperties().getProperty('APOLLO_API_KEY');
  if (!key) throw new Error('APOLLO_API_KEY not set in Script Properties');
  return key;
}

// ── STEP 1: Repair Contact IDs ────────────────────────────────────────────────
function repairContactIds() {
  var sheet   = SpreadsheetApp.openById(REPAIR_SHEET_ID).getSheetByName('Contacts');
  var data    = sheet.getDataRange().getValues();
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

  var seenIds = {}, repaired = 0, updates = [];
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
  updates.forEach(function(u) { sheet.getRange(u.rowIndex, idCol + 1).setValue(u.newId); });
  Logger.log('Done. ' + repaired + ' Contact IDs repaired.');
}

// ── STEP 2a: Push ALL contacts ────────────────────────────────────────────────
function pushAllContactsToRailway() { pushContactsFromRow(1); }

// ── STEP 2b: Resume from a specific contact index ────────────────────────────
function pushContactsFromRow(startContactIndex) {
  var sheet   = SpreadsheetApp.openById(REPAIR_SHEET_ID).getSheetByName('Contacts');
  var data    = sheet.getDataRange().getValues();
  var headers = data[0];
  var col = {
    contact_id: headers.indexOf('Contact ID'), full_name: headers.indexOf('Full Name'),
    title_role: headers.indexOf('Title / Role'), organization: headers.indexOf('Organization'),
    how_we_met: headers.indexOf('How We Met'), venture: headers.indexOf('Venture'),
    what_building: headers.indexOf("What They're Building"), what_need: headers.indexOf('What They Need'),
    what_offer: headers.indexOf('What They Offer'), relationship_health: headers.indexOf('Relationship Health'),
    activation_potential: headers.indexOf('Activation Potential'), notes: headers.indexOf('Notes'),
  };

  var allContacts = data.slice(1).filter(function(r) { return r[col.full_name]; }).map(function(r) {
    return {
      contact_id: String(r[col.contact_id]||''), full_name: String(r[col.full_name]||''),
      title_role: String(r[col.title_role]||''), organization: String(r[col.organization]||''),
      how_we_met: String(r[col.how_we_met]||''), venture: String(r[col.venture]||''),
      what_building: String(r[col.what_building]||''), what_need: String(r[col.what_need]||''),
      what_offer: String(r[col.what_offer]||''), relationship_health: String(r[col.relationship_health]||''),
      activation_potential: String(r[col.activation_potential]||''), notes: String(r[col.notes]||''),
    };
  });

  var start = (startContactIndex || 1) - 1;
  var contacts = allContacts.slice(start);
  Logger.log('Resuming from contact ' + (start + 1) + '. Pushing ' + contacts.length + ' contacts.');

  var totalSuccess = 0, totalSkipped = 0, totalErrors = 0;
  var key = _getRailwayKey();

  for (var i = 0; i < contacts.length; i += BATCH_SIZE) {
    var batch = contacts.slice(i, i + BATCH_SIZE);
    var batchNum = Math.floor(i / BATCH_SIZE) + 1;
    try {
      var res = UrlFetchApp.fetch(RAILWAY_API_BASE + '/contact/bulk', {
        method: 'post', muteHttpExceptions: true,
        headers: { 'Content-Type': 'application/json', 'X-API-Key': key },
        payload: JSON.stringify({ contacts: batch })
      });
      var result = JSON.parse(res.getContentText());
      totalSuccess += result.success || 0;
      totalSkipped += result.skipped || 0;
      totalErrors  += (result.errors || []).length;
      Logger.log('Batch ' + batchNum + ': ' + (result.success||0) + ' ok, ' + (result.skipped||0) + ' skipped');
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
  var counts  = {}, blank = 0;
  data.slice(1).forEach(function(row) {
    var id = String(row[idCol] || '');
    if (!id) { blank++; return; }
    counts[id] = (counts[id] || 0) + 1;
  });
  var unique     = Object.keys(counts).filter(function(id) { return counts[id] === 1; }).length;
  var duplicated = Object.keys(counts).filter(function(id) { return counts[id] > 1; }).length;
  Logger.log('Total rows: ' + (data.length - 1));
  Logger.log('Unique IDs: ' + unique);
  Logger.log('Duplicate IDs: ' + duplicated);
  Logger.log('Blank IDs: ' + blank);
  Logger.log(duplicated === 0 ? 'ALL CLEAN - ready for Apollo enrichment' : 'STILL HAS DUPLICATES - run repairContactIds()');
}

// ── STEP 4: Score Relationship Health + Activation Potential ──────────────────
function scoreRelationshipHealth(forceOverwrite) {
  var sheet   = SpreadsheetApp.openById(REPAIR_SHEET_ID).getSheetByName('Contacts');
  var data    = sheet.getDataRange().getValues();
  var headers = data[0];
  var col = {
    full_name: headers.indexOf('Full Name'), how_we_met: headers.indexOf('How We Met'),
    relationship_health: headers.indexOf('Relationship Health'),
    activation_potential: headers.indexOf('Activation Potential'),
    last_contacted: headers.indexOf('Last Contacted'), notes: headers.indexOf('Notes'),
    email: headers.indexOf('Email'), next_action: headers.indexOf('Next Action'),
    venture: headers.indexOf('Venture'), initiative: headers.indexOf('Initiative'),
  };

  var now = new Date().getTime(), day = 86400000, scored = 0, skipped = 0;
  var healthUpdates = [], activationUpdates = [];

  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    if (!row[col.full_name]) continue;
    var existingHealth     = String(row[col.relationship_health]  || '').trim();
    var existingActivation = String(row[col.activation_potential] || '').trim();
    if (!forceOverwrite && existingHealth && existingActivation) { skipped++; continue; }

    var howMet     = String(row[col.how_we_met]  || '').toLowerCase();
    var notes      = String(row[col.notes]       || '');
    var email      = String(row[col.email]       || '').trim();
    var nextAction = String(row[col.next_action] || '').trim();
    var venture    = String(row[col.venture]     || '').trim();
    var initiative = String(row[col.initiative]  || '').trim();

    var lastContactedMs = 0;
    if (row[col.last_contacted]) {
      var d = new Date(row[col.last_contacted]);
      if (!isNaN(d.getTime())) lastContactedMs = d.getTime();
    }
    var daysSinceContact = lastContactedMs ? (now - lastContactedMs) / day : 9999;
    var substantiveNotes = notes.length > 60 && !notes.match(/^LinkedIn connection since/i);

    var health;
    if (daysSinceContact <= 30 && substantiveNotes)                              health = 'Hot';
    else if (daysSinceContact <= 30 || (daysSinceContact <= 90 && substantiveNotes)) health = 'Warm';
    else if (howMet && !howMet.startsWith('linkedin') && howMet !== '')          health = 'Warm';
    else if (daysSinceContact <= 180 || substantiveNotes)                        health = 'Lukewarm';
    else                                                                          health = 'Cold';

    var activation;
    if (initiative || venture)                              activation = 'Super Connector';
    else if (health === 'Hot' || health === 'Warm')         activation = email ? 'High' : 'Medium';
    else if (substantiveNotes || nextAction || email)       activation = 'Medium';
    else                                                    activation = 'Low';

    if (forceOverwrite || !existingHealth)     healthUpdates.push({ row: i + 1, val: health });
    if (forceOverwrite || !existingActivation) activationUpdates.push({ row: i + 1, val: activation });
    scored++;
  }

  healthUpdates.forEach(function(u)     { sheet.getRange(u.row, col.relationship_health  + 1).setValue(u.val); });
  activationUpdates.forEach(function(u) { sheet.getRange(u.row, col.activation_potential + 1).setValue(u.val); });

  Logger.log('Scored: ' + scored + ' | Skipped: ' + skipped);
  Logger.log('Health updates: ' + healthUpdates.length + ' | Activation updates: ' + activationUpdates.length);
  Logger.log('Done. Run pushContactsFromRow(1) to re-push scored contacts to Railway.');
}

// ── STEP 5: Apollo Enrichment ─────────────────────────────────────────────────
// Enriches contacts that have Relationship Health = Hot, Warm, or Lukewarm
// Uses Apollo People Enrichment API (1 credit per contact)
// Run enrichWithApollo() to start, enrichWithApolloFromRow(N) to resume after timeout

function enrichWithApollo() { enrichWithApolloFromRow(1); }

function enrichWithApolloFromRow(startRow) {
  var sheet   = SpreadsheetApp.openById(REPAIR_SHEET_ID).getSheetByName('Contacts');
  var data    = sheet.getDataRange().getValues();
  var headers = data[0];

  var col = {
    contact_id:          headers.indexOf('Contact ID'),
    full_name:           headers.indexOf('Full Name'),
    title_role:          headers.indexOf('Title / Role'),
    organization:        headers.indexOf('Organization'),
    email:               headers.indexOf('Email'),
    phone:               headers.indexOf('Phone'),
    linkedin_url:        headers.indexOf('LinkedIn URL'),
    relationship_health: headers.indexOf('Relationship Health'),
    notes:               headers.indexOf('Notes'),
  };

  // Only enrich Hot, Warm, Lukewarm contacts — preserve Apollo credits
  var ENRICH_HEALTH = ['Hot', 'Warm', 'Lukewarm'];

  // Build list of contacts to enrich, starting from startRow (1-based data row)
  var toEnrich = [];
  for (var i = Math.max(1, startRow); i < data.length; i++) {
    var row    = data[i];
    var name   = String(row[col.full_name]           || '').trim();
    var health = String(row[col.relationship_health] || '').trim();
    var hasEmail = String(row[col.email]             || '').trim();

    if (!name) continue;
    if (ENRICH_HEALTH.indexOf(health) < 0) continue; // skip Cold contacts
    if (hasEmail) continue;                           // already has email, skip

    toEnrich.push({ sheetRow: i + 1, contact_id: String(row[col.contact_id]||''), full_name: name, organization: String(row[col.organization]||''), title_role: String(row[col.title_role]||'') });
  }

  Logger.log('Contacts eligible for enrichment: ' + toEnrich.length);
  if (toEnrich.length === 0) { Logger.log('Nothing to enrich. All eligible contacts already have emails or are Cold.'); return; }

  var apolloKey    = _getApolloKey();
  var railwayKey   = _getRailwayKey();
  var enriched     = 0;
  var notFound     = 0;
  var errors       = 0;

  for (var j = 0; j < toEnrich.length; j++) {
    var contact = toEnrich[j];

    try {
      // Call Apollo People Enrichment
      var payload = { first_name: '', last_name: '' };
      var nameParts = contact.full_name.trim().split(' ');
      payload.first_name = nameParts[0] || '';
      payload.last_name  = nameParts.slice(1).join(' ') || '';
      if (contact.organization) payload.organization_name = contact.organization;

      var apolloRes = UrlFetchApp.fetch('https://api.apollo.io/v1/people/match', {
        method: 'post', muteHttpExceptions: true,
        headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-cache' },
        payload: JSON.stringify(Object.assign({ api_key: apolloKey }, payload))
      });

      var apolloResult = JSON.parse(apolloRes.getContentText());
      var person = apolloResult.person;

      if (!person) { notFound++; continue; }

      // Extract enriched fields
      var enrichedEmail   = (person.email                              || '').trim();
      var enrichedPhone   = (person.sanitized_phone                   || '').trim();
      var enrichedLinkedIn = (person.linkedin_url                     || '').trim();
      var enrichedTitle   = (person.title                             || contact.title_role).trim();
      var enrichedOrg     = (person.organization && person.organization.name ? person.organization.name : contact.organization).trim();

      // Write back to sheet
      if (enrichedEmail    && col.email        >= 0) sheet.getRange(contact.sheetRow, col.email        + 1).setValue(enrichedEmail);
      if (enrichedPhone    && col.phone        >= 0) sheet.getRange(contact.sheetRow, col.phone        + 1).setValue(enrichedPhone);
      if (enrichedLinkedIn && col.linkedin_url >= 0) sheet.getRange(contact.sheetRow, col.linkedin_url + 1).setValue(enrichedLinkedIn);
      if (enrichedTitle    && col.title_role   >= 0) sheet.getRange(contact.sheetRow, col.title_role   + 1).setValue(enrichedTitle);
      if (enrichedOrg      && col.organization >= 0) sheet.getRange(contact.sheetRow, col.organization + 1).setValue(enrichedOrg);

      // Push updated contact to Railway to re-vectorize
      var updatedRow = sheet.getRange(contact.sheetRow, 1, 1, headers.length).getValues()[0];
      var railwayPayload = {
        contact_id:           String(updatedRow[col.contact_id]           || ''),
        full_name:            String(updatedRow[col.full_name]            || ''),
        title_role:           enrichedTitle || String(updatedRow[col.title_role] || ''),
        organization:         enrichedOrg  || String(updatedRow[col.organization] || ''),
        how_we_met:           String(updatedRow[headers.indexOf('How We Met')] || ''),
        venture:              String(updatedRow[headers.indexOf('Venture')]    || ''),
        relationship_health:  String(updatedRow[col.relationship_health]   || ''),
        activation_potential: String(updatedRow[headers.indexOf('Activation Potential')] || ''),
        notes:                String(updatedRow[col.notes] || ''),
      };

      UrlFetchApp.fetch(RAILWAY_API_BASE + '/contact/' + contact.contact_id, {
        method: 'put', muteHttpExceptions: true,
        headers: { 'Content-Type': 'application/json', 'X-API-Key': railwayKey },
        payload: JSON.stringify(railwayPayload)
      });

      enriched++;
      if (enriched % 10 === 0) Logger.log('Enriched ' + enriched + ' contacts so far...');

    } catch (e) {
      Logger.log('Error enriching ' + contact.full_name + ': ' + e.message);
      errors++;
    }

    Utilities.sleep(500); // Apollo rate limit
  }

  Logger.log('=== APOLLO DONE ===');
  Logger.log('Enriched: ' + enriched + ' | Not found: ' + notFound + ' | Errors: ' + errors);
  Logger.log('Credits used: ~' + enriched + ' lead credits');
}

// ── ADD NEW CONTACT (single contact — use from web app or manually) ───────────
// Adds to Sheet + pushes to Railway immediately
function addContact(contactData) {
  var sheet   = SpreadsheetApp.openById(REPAIR_SHEET_ID).getSheetByName('Contacts');
  var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];

  var newId  = 'C' + Date.now();
  var newRow = headers.map(function(h) {
    if (h === 'Contact ID') return newId;
    if (h === 'Added Date') return new Date().toISOString();
    return contactData[h] || '';
  });

  sheet.appendRow(newRow);

  // Push to Railway immediately
  var key = _getRailwayKey();
  UrlFetchApp.fetch(RAILWAY_API_BASE + '/contact', {
    method: 'post', muteHttpExceptions: true,
    headers: { 'Content-Type': 'application/json', 'X-API-Key': key },
    payload: JSON.stringify({
      contact_id:           newId,
      full_name:            contactData['Full Name']            || '',
      title_role:           contactData['Title / Role']         || '',
      organization:         contactData['Organization']         || '',
      how_we_met:           contactData['How We Met']           || '',
      venture:              contactData['Venture']              || '',
      what_building:        contactData["What They're Building"] || '',
      what_need:            contactData['What They Need']       || '',
      what_offer:           contactData['What They Offer']      || '',
      relationship_health:  contactData['Relationship Health']  || '',
      activation_potential: contactData['Activation Potential'] || '',
      notes:                contactData['Notes']                || '',
    })
  });

  Logger.log('Added contact: ' + contactData['Full Name'] + ' (' + newId + ')');
  return newId;
}
