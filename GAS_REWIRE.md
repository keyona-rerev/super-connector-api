# GAS Rewire — Copy-Paste Reference

Open the GAS editor at:
https://script.google.com/home/projects/1UeO72LgmCgEhr534Aw2ouj7lHKFiXe0mbGSCaFjsf1bphf510SOnkV4e/edit

For each file below:
- If the file exists: select all content and replace with the code below
- If it doesn't exist: click + Add a file, name it, paste the code

Files to DELETE: Data.gs, Email.gs (content replaced by Phoebe.gs below)

---

## Railway.gs (NEW FILE)

```javascript
const Railway = (function() {
  var BASE = 'https://super-connector-api-production.up.railway.app';
  function _key() {
    var k = PropertiesService.getScriptProperties().getProperty('SC_API_KEY');
    if (!k) throw new Error('SC_API_KEY not set in Script Properties');
    return k;
  }
  function _headers() { return {'Content-Type':'application/json','X-API-Key':_key()}; }
  function _fetch(path, opts) {
    var res = UrlFetchApp.fetch(BASE + path, Object.assign({muteHttpExceptions:true,headers:_headers()}, opts||{}));
    var code = res.getResponseCode();
    var body = JSON.parse(res.getContentText());
    if (code >= 400) throw new Error(body.detail || 'Railway error ' + code);
    return body;
  }
  function getInitiatives() { return _fetch('/initiatives').data || []; }
  function getInitiative(id) { return _fetch('/initiative/' + id); }
  function patchInitiativeStatus(id, status) {
    return _fetch('/initiative/' + id + '/status', {method:'post',payload:JSON.stringify({status:status})});
  }
  function updateInitiative(id, data) {
    return _fetch('/initiative/' + id, {method:'put',payload:JSON.stringify(data)});
  }
  function getOpenActionItems(dueBefore) {
    var qs = dueBefore ? '?due_before=' + dueBefore : '';
    return _fetch('/action-items' + qs).data || [];
  }
  function createActionItem(data) {
    return _fetch('/action-item', {method:'post',payload:JSON.stringify(data)});
  }
  function patchActionItemStatus(id, status, completedDate, googleTaskId) {
    var body = {status:status};
    if (completedDate) body.completed_date = completedDate;
    if (googleTaskId) body.google_task_id = googleTaskId;
    return _fetch('/action-item/' + id + '/status', {method:'post',payload:JSON.stringify(body)});
  }
  function getActionItemByGoogleTaskId(taskId) {
    try { return _fetch('/action-item/by-google-task/' + taskId).data; } catch(e) { return null; }
  }
  function getStakeholdersForInitiative(id) { return _fetch('/initiative/' + id + '/stakeholders').data || []; }
  function getContactInitiatives(id) { return _fetch('/contact/' + id + '/initiatives').data || []; }
  function updateStakeholderEngagement(id, status, notes) {
    return _fetch('/stakeholder/' + id + '/engagement', {method:'post',payload:JSON.stringify({engagement_status:status,notes:notes||''})});
  }
  function searchContacts(query, topK) {
    return _fetch('/search', {method:'post',payload:JSON.stringify({query:query,top_k:topK||10})}).results || [];
  }
  function getContact(id) { return _fetch('/contact/' + id).data; }
  function updateContact(id, data) { return _fetch('/contact/' + id, {method:'put',payload:JSON.stringify(data)}); }
  return {
    getInitiatives:getInitiatives, getInitiative:getInitiative,
    patchInitiativeStatus:patchInitiativeStatus, updateInitiative:updateInitiative,
    getOpenActionItems:getOpenActionItems, createActionItem:createActionItem,
    patchActionItemStatus:patchActionItemStatus, getActionItemByGoogleTaskId:getActionItemByGoogleTaskId,
    getStakeholdersForInitiative:getStakeholdersForInitiative, getContactInitiatives:getContactInitiatives,
    updateStakeholderEngagement:updateStakeholderEngagement,
    searchContacts:searchContacts, getContact:getContact, updateContact:updateContact
  };
})();
```

---

## Claude.gs (REPLACE existing content)

```javascript
var ClaudeAPI = (function() {
  function _key() {
    var k = PropertiesService.getScriptProperties().getProperty('ANTHROPIC_API_KEY');
    if (!k) throw new Error('ANTHROPIC_API_KEY not set in Script Properties');
    return k;
  }
  function call(prompt, maxTokens) {
    var res = UrlFetchApp.fetch('https://api.anthropic.com/v1/messages', {
      method:'post', muteHttpExceptions:true,
      headers:{'Content-Type':'application/json','x-api-key':_key(),'anthropic-version':'2023-06-01'},
      payload:JSON.stringify({model:'claude-sonnet-4-20250514',max_tokens:maxTokens||1000,messages:[{role:'user',content:prompt}]})
    });
    var body = JSON.parse(res.getContentText());
    if (body.error) throw new Error('Claude error: ' + body.error.message);
    return body.content[0].text;
  }
  function parseReply(emailText, initiatives) {
    var initList = initiatives.slice(0,15).map(function(i){return i.initiative_id+': '+i.initiative_name;}).join('\n');
    var prompt = 'You are Phoebe, Keyona Meeks AI chief of staff. She replied to a check-in email.\n\nActive initiatives:\n'+initList+'\n\nParse her reply. Return ONLY valid JSON, no preamble:\n{"updates":[{"type":"action_done","description":"...","action_id":"id or null"},{"type":"action_new","description":"...","priority":"High|Medium|Low","due_date":"YYYY-MM-DD or null","initiative_id":"id or null"},{"type":"initiative_status","initiative_id":"id","new_status":"Active|Planning|Paused|Blocked|Complete"},{"type":"note","text":"..."}],"summary":"one sentence"}\n\nEmail:\n'+emailText;
    var raw = call(prompt, 1000);
    var match = raw.match(/\{[\s\S]*\}/);
    if (!match) throw new Error('No JSON in Claude response');
    return JSON.parse(match[0]);
  }
  function generateCheckIn(dayType, initiatives, overdueItems, meetings) {
    var top = initiatives.filter(function(i){return ['Active','Blocked'].indexOf(i.status)>=0;})
      .sort(function(a,b){var o={Critical:4,High:3,Medium:2,Low:1,Parked:0};return (o[b.priority]||0)-(o[a.priority]||0);})
      .slice(0,3);
    var overdueText = overdueItems.length
      ? overdueItems.map(function(a){return '- '+a.description+' (due '+(a.due_date||'').substring(0,10)+')';}).join('\n')
      : 'None - queue is clear';
    var meetingText = (meetings&&meetings.length)
      ? meetings.map(function(m){return '- '+m.title+' - '+m.attendees;}).join('\n')
      : 'No meetings with known stakeholders';
    var prompt = 'You are Phoebe, Keyona Meeks AI chief of staff. Write a '+dayType+' priority check-in email.\nTone: Direct, warm, smart. No fluff.\n\nTop 3 active priorities:\n'
      +top.map(function(i){return '- '+i.initiative_name+' ('+i.venture+') - '+i.status+', '+i.priority+' priority\n  Goal: '+(i.goal||'not set')+'\n  Notes: '+(i.notes||'').substring(0,120);}).join('\n\n')
      +'\n\nOverdue:\n'+overdueText+'\n\nUpcoming meetings:\n'+meetingText
      +'\n\nWrite email body as HTML inner content only. End with: Reply to this email with updates - Phoebe will parse and update the system. Sign as Phoebe.';
    return call(prompt, 1500);
  }
  return {call:call, parseReply:parseReply, generateCheckIn:generateCheckIn};
})();
```

---

## Phoebe.gs (RENAME Email.gs → Phoebe, REPLACE all content)

```javascript
function sendMondayCheckIn()   { _sendCheckIn('Monday'); }
function sendThursdayCheckIn() { _sendCheckIn('Thursday'); }
function scanStatusDecay()     { _scanDecay(); }
function processReplies()      { _processInboxReplies(); }
function testCheckIn()         { _sendCheckIn('Test'); }

function _sendCheckIn(dayType) {
  try {
    var userEmail   = Session.getActiveUser().getEmail();
    var initiatives = Railway.getInitiatives();
    var today       = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd');
    var overdue     = Railway.getOpenActionItems(today);
    var meetings    = _getUpcomingMeetings();
    var bodyHtml    = ClaudeAPI.generateCheckIn(dayType, initiatives, overdue, meetings);
    var subject     = 'Phoebe ' + dayType + ' Check-In - ' + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'MMM d');
    GmailApp.sendEmail(userEmail, subject, 'Enable HTML to view.', {htmlBody: _wrapEmail(subject, bodyHtml), replyTo: userEmail});
    Logger.log('Check-in sent to ' + userEmail);
  } catch(e) { Logger.log('Check-in failed: ' + e.message); }
}

function _processInboxReplies() {
  try {
    _ensureLabel('Phoebe/Replies'); _ensureLabel('Phoebe/Processed');
    var repliesLabel   = GmailApp.getUserLabelByName('Phoebe/Replies');
    var processedLabel = GmailApp.getUserLabelByName('Phoebe/Processed');
    var threads        = repliesLabel.getThreads(0, 5);
    if (!threads.length) { Logger.log('No new replies'); return; }
    var initiatives = Railway.getInitiatives();
    threads.forEach(function(thread) {
      try {
        var messages = thread.getMessages();
        var reply    = messages[messages.length - 1];
        if (!reply.isUnread()) return;
        var parsed = ClaudeAPI.parseReply(reply.getPlainBody(), initiatives);
        _applyUpdates(parsed);
        reply.markRead();
        thread.removeLabel(repliesLabel);
        thread.addLabel(processedLabel);
        Logger.log('Processed: ' + parsed.summary);
      } catch(e) { Logger.log('Reply failed: ' + e.message); }
    });
  } catch(e) { Logger.log('processReplies failed: ' + e.message); }
}

function _applyUpdates(parsed) {
  (parsed.updates || []).forEach(function(u) {
    try {
      if (u.type === 'action_done' && u.action_id) {
        Railway.patchActionItemStatus(u.action_id, 'Complete',
          Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd'));
      } else if (u.type === 'action_new') {
        Railway.createActionItem({description:u.description, priority:u.priority||'Medium',
          due_date:u.due_date||null, initiative_id:u.initiative_id||'SPRINT',
          source:'Phoebe', phoebe_tracking:true});
      } else if (u.type === 'initiative_status' && u.initiative_id && u.new_status) {
        Railway.patchInitiativeStatus(u.initiative_id, u.new_status);
      }
    } catch(e) { Logger.log('Apply failed: ' + e.message); }
  });
}

function _scanDecay() {
  try {
    var initiatives = Railway.getInitiatives();
    var now = new Date().getTime();
    var cadenceDays = {'Daily':1,'Every 2-3 days':3,'Weekly':7,'Biweekly':14,'Monthly':30};
    var stale = [];
    initiatives.forEach(function(i) {
      if (['Active','Blocked'].indexOf(i.status) < 0) return;
      if (!i.phoebe_cadence || i.phoebe_cadence === 'None') return;
      var days = cadenceDays[i.phoebe_cadence] || 7;
      var lastCheck = new Date(i.last_phoebe_checkin || i.updated_at || 0).getTime();
      if ((now - lastCheck) / 86400000 > days * 1.5) stale.push(i);
    });
    if (!stale.length) { Logger.log('No stale initiatives'); return; }
    var rows = stale.map(function(i) {
      return '<tr><td style="padding:8px;border-bottom:1px solid #eee">'+i.initiative_name+'</td><td style="padding:8px;border-bottom:1px solid #eee">'+i.venture+'</td></tr>';
    }).join('');
    var body = '<h2 style="color:#e74c3c">'+stale.length+' initiative(s) overdue for check-in</h2><table style="width:100%;border-collapse:collapse"><thead><tr><th style="padding:8px;text-align:left">Initiative</th><th style="padding:8px;text-align:left">Venture</th></tr></thead><tbody>'+rows+'</tbody></table><p style="margin-top:16px">Reply with a quick update and Phoebe will process it.</p>';
    var userEmail = Session.getActiveUser().getEmail();
    GmailApp.sendEmail(userEmail, 'Phoebe Status Decay Alert', '', {htmlBody: _wrapEmail('Status Decay Alert', body)});
    Logger.log('Decay alert sent for ' + stale.length + ' initiatives');
  } catch(e) { Logger.log('Decay scan failed: ' + e.message); }
}

function _getUpcomingMeetings() {
  try {
    var now = new Date(); var end = new Date(now.getTime() + 14*86400000);
    return CalendarApp.getDefaultCalendar().getEvents(now, end)
      .filter(function(e){return !e.isAllDayEvent() && e.getGuestList().length > 0;})
      .slice(0, 5)
      .map(function(e){
        return {title:e.getTitle(), attendees:e.getGuestList().map(function(g){return g.getName()||g.getEmail();}).join(', ')};
      });
  } catch(e) { return []; }
}

function _wrapEmail(title, bodyHtml) {
  var tz = Session.getScriptTimeZone();
  return '<!DOCTYPE html><html><body style="font-family:-apple-system,sans-serif;background:#F5F4EF;margin:0;padding:0"><div style="max-width:620px;margin:20px auto;background:#FDFCF8;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08)"><div style="background:#D97757;padding:24px 28px"><h1 style="color:#fff;margin:0;font-size:20px;font-weight:500">'+title+'</h1><p style="color:rgba(255,255,255,0.8);margin:4px 0 0;font-size:13px">'+Utilities.formatDate(new Date(),tz,'EEEE, MMMM d yyyy')+'</p></div><div style="padding:28px">'+bodyHtml+'</div><div style="padding:16px 28px;border-top:1px solid #E5E3DA;text-align:center"><p style="color:#9C9A93;font-size:12px;margin:0">Phoebe &middot; <a href="https://keyona-rerev.github.io/super-connector-app" style="color:#D97757">Open Dashboard</a></p></div></div></body></html>';
}

function _ensureLabel(name) {
  try { GmailApp.getUserLabelByName(name); } catch(e) { try { GmailApp.createLabel(name); } catch(e2) {} }
}
```

---

## CalendarBriefing.gs (REPLACE existing content)

```javascript
function scanCalendarForMeetings() {
  try {
    var today = new Date(); var tomorrow = new Date(today.getTime() + 86400000);
    var allEvents = _getCalEvents(today).concat(_getCalEvents(tomorrow));
    if (!allEvents.length) { Logger.log('No meetings'); return; }
    var enriched = [];
    allEvents.forEach(function(event) {
      if (!event.guests.length) return;
      var matches = [];
      event.guests.forEach(function(g) {
        if (!g.name) return;
        try {
          var r = Railway.searchContacts(g.name, 3);
          if (r.length && r[0].similarity > 0.7) matches.push(r[0]);
        } catch(e) {}
      });
      if (!matches.length) return;
      var enrichedContacts = matches.map(function(c) {
        try { var full = Railway.getContact(c.contact_id); return Object.assign({},c,{initiative_links:full?(full.initiative_links||[]):[]}); }
        catch(e) { return Object.assign({},c,{initiative_links:[]}); }
      });
      enriched.push({event:event, contacts:enrichedContacts});
    });
    if (!enriched.length) { Logger.log('No matched contacts'); return; }
    _sendCalBriefing(enriched);
    Logger.log('Briefing sent for ' + enriched.length + ' event(s)');
  } catch(e) { Logger.log('Calendar scan failed: ' + e.message); }
}

function _sendCalBriefing(enrichedEvents) {
  var userEmail = Session.getActiveUser().getEmail();
  var tz = Session.getScriptTimeZone();
  var todayStr = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  var sections = enrichedEvents.map(function(item) {
    var ev = item.event; var contacts = item.contacts;
    var timeStr = Utilities.formatDate(ev.startTime, tz, 'h:mm a');
    var dayLabel = Utilities.formatDate(ev.startTime, tz, 'yyyy-MM-dd') === todayStr ? 'Today' : 'Tomorrow';
    var blocks = contacts.map(function(c) {
      var roleOrg = [c.title_role,c.organization].filter(Boolean).join(' · ');
      var links = c.initiative_links || [];
      return '<div style="background:#F5F4EF;border-radius:8px;padding:16px;margin-bottom:12px"><div style="font-weight:600;font-size:15px">'+_cesc(c.full_name||'—')+'</div><div style="color:#6B6860;font-size:13px;margin-bottom:8px">'+_cesc(roleOrg||'—')+'</div>'+(links.length?'<div style="font-size:12px;font-weight:700;text-transform:uppercase;color:#9C9A93;margin-bottom:6px">In '+links.length+' Initiative(s)</div>'+links.map(function(l){return '<div style="font-size:13px;color:#D97757">◈ '+_cesc(l.initiative_id)+' — '+_cesc(l.role||'Stakeholder')+'</div>';}).join(''):'<div style="font-size:12px;color:#9C9A93">Not linked to any initiatives</div>')+'</div>';
    }).join('');
    return '<div style="margin-bottom:28px"><div style="font-size:16px;font-weight:600;margin-bottom:12px">'+dayLabel+' '+timeStr+' — '+_cesc(ev.title)+'</div>'+blocks+'</div>';
  }).join('<hr style="border:none;border-top:1px solid #E5E3DA;margin:24px 0">');
  var body = '<h2 style="font-size:22px;font-weight:400;margin-bottom:16px">Your meetings today involve people you know.</h2><p style="color:#6B6860;font-size:13px;margin-bottom:24px">Reply with meeting notes — Phoebe will update your dashboard.</p>'+sections;
  var subject = 'Phoebe Meeting Brief — ' + Utilities.formatDate(new Date(), tz, 'MMM d');
  GmailApp.sendEmail(userEmail, subject, 'Enable HTML to view.', {htmlBody:_calWrap(subject,body), replyTo:userEmail});
}

function _getCalEvents(date) {
  try {
    var end = new Date(date.getTime()); end.setHours(23,59,59,999);
    return CalendarApp.getDefaultCalendar().getEvents(date, end)
      .filter(function(e){return !e.isAllDayEvent();})
      .map(function(e){return {title:e.getTitle(),startTime:e.getStartTime(),guests:e.getGuestList().map(function(g){return {email:g.getEmail(),name:g.getName()};})};});
  } catch(e) { return []; }
}

function _cesc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function _calWrap(title, bodyHtml) {
  var tz = Session.getScriptTimeZone();
  return '<!DOCTYPE html><html><body style="font-family:-apple-system,sans-serif;background:#F5F4EF;margin:0;padding:0"><div style="max-width:620px;margin:20px auto;background:#FDFCF8;border-radius:12px;overflow:hidden"><div style="background:#D97757;padding:24px 28px"><h1 style="color:#fff;margin:0;font-size:20px;font-weight:500">'+title+'</h1><p style="color:rgba(255,255,255,0.8);margin:4px 0 0;font-size:13px">'+Utilities.formatDate(new Date(),tz,'EEEE, MMMM d yyyy')+'</p></div><div style="padding:28px">'+bodyHtml+'</div><div style="padding:16px 28px;border-top:1px solid #E5E3DA;text-align:center"><p style="color:#9C9A93;font-size:12px;margin:0">Phoebe &middot; <a href="https://keyona-rerev.github.io/super-connector-app" style="color:#D97757">Open Dashboard</a></p></div></div></body></html>';
}

function installCalendarTrigger() {
  var triggers = ScriptApp.getProjectTriggers();
  if (!triggers.some(function(t){return t.getHandlerFunction()==='scanCalendarForMeetings';})) {
    ScriptApp.newTrigger('scanCalendarForMeetings').timeBased().atHour(7).everyDays(1).create();
    Logger.log('Calendar trigger: Daily 7am');
  }
}

function testCalendarBriefing() { scanCalendarForMeetings(); }
```

---

## TaskSync.gs (NEW FILE)

```javascript
var TASK_LIST_NAME = 'Phoebe Action Items';

function syncTasks() {
  try { _pushNewItemsToTasks(); _pullCompletedTasksToRailway(); Logger.log('Task sync complete'); }
  catch(e) { Logger.log('Task sync failed: ' + e.message); }
}

function _pushNewItemsToTasks() {
  var listId = _getOrCreateTaskList();
  var items = Railway.getOpenActionItems().filter(function(a){return a.phoebe_tracking && !a.google_task_id;});
  items.forEach(function(item) {
    try {
      var task = Tasks.Tasks.insert({
        title: item.description,
        notes: [item.initiative_id, item.action_type].filter(Boolean).join(' · '),
        due: item.due_date ? new Date(item.due_date).toISOString() : undefined
      }, listId);
      Railway.patchActionItemStatus(item.action_id, item.status, null, task.id);
      Logger.log('Pushed: ' + item.description);
    } catch(e) { Logger.log('Push failed: ' + e.message); }
  });
}

function _pullCompletedTasksToRailway() {
  var listId = _getOrCreateTaskList(); var pageToken;
  do {
    var res = Tasks.Tasks.list(listId, {showCompleted:true,showHidden:true,maxResults:50,pageToken:pageToken});
    (res.items||[]).forEach(function(task) {
      if (task.status !== 'completed') return;
      try {
        var item = Railway.getActionItemByGoogleTaskId(task.id);
        if (!item || item.status === 'Complete') return;
        var completed = task.completed
          ? Utilities.formatDate(new Date(task.completed), Session.getScriptTimeZone(), 'yyyy-MM-dd')
          : Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd');
        Railway.patchActionItemStatus(item.action_id, 'Complete', completed);
        Logger.log('Marked complete: ' + item.description);
      } catch(e) { Logger.log('Pull failed: ' + e.message); }
    });
    pageToken = res.nextPageToken;
  } while(pageToken);
}

function _getOrCreateTaskList() {
  var lists = Tasks.Tasklists.list().items || [];
  var existing = lists.filter(function(l){return l.title===TASK_LIST_NAME;})[0];
  if (existing) return existing.id;
  return Tasks.Tasklists.insert({title:TASK_LIST_NAME}).id;
}

function testTaskSync() { syncTasks(); }
```

---

## Code.gs (REPLACE existing content)

```javascript
function onOpen() {
  try {
    SpreadsheetApp.getUi().createMenu('Phoebe')
      .addItem('Setup All Triggers', 'setupAllTriggers')
      .addItem('Test: Send Check-In Now', 'testCheckIn')
      .addItem('Test: Calendar Briefing', 'testCalendarBriefing')
      .addItem('Test: Task Sync', 'testTaskSync')
      .addToUi();
  } catch(e) {}
}

function setupAllTriggers() {
  var names = ['sendMondayCheckIn','sendThursdayCheckIn','scanStatusDecay','processReplies',
               'scanCalendarForMeetings','syncTasks'];
  ScriptApp.getProjectTriggers().forEach(function(t){
    if (names.indexOf(t.getHandlerFunction()) >= 0) ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('sendMondayCheckIn').timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(8).create();
  ScriptApp.newTrigger('sendThursdayCheckIn').timeBased().onWeekDay(ScriptApp.WeekDay.THURSDAY).atHour(8).create();
  ScriptApp.newTrigger('scanStatusDecay').timeBased().everyHours(6).create();
  ScriptApp.newTrigger('processReplies').timeBased().everyMinutes(30).create();
  ScriptApp.newTrigger('scanCalendarForMeetings').timeBased().atHour(7).everyDays(1).create();
  ScriptApp.newTrigger('syncTasks').timeBased().everyMinutes(15).create();
  try {
    SpreadsheetApp.getUi().alert('All Phoebe triggers set:\n- Mon/Thu 8am: check-ins\n- Every 6h: decay scan\n- Every 30min: reply processing\n- Daily 7am: calendar briefing\n- Every 15min: Tasks sync');
  } catch(e) { Logger.log('Triggers installed'); }
}
```

---

After pasting all files, also make sure Script Properties has:
- SC_API_KEY = your Railway key
- ANTHROPIC_API_KEY = your Anthropic key

Then run `setupAllTriggers` from the Phoebe menu. Done.
