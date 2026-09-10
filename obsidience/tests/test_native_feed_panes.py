"""Native feed navigation, settings and shared Reader render against isolated transport."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import pytest

SOURCE = Path(__file__).parents[1] / 'shell/qml/panes/feeds/FeedsPane.qml'

@pytest.mark.parametrize('pane_width', [320, 640, 1040])
def test_native_feed_panes_and_shared_reader(tmp_path, pane_width):
    """Load the real pane with only transport addresses replaced by an isolated fixture."""
    import http.server
    import os
    import shutil
    import threading
    import pytest

    qml = shutil.which('qml6')
    if qml is None:
        pytest.skip('qml6 is not installed')
    requests = []
    payload = {'revision': 3, 'connections': [
        {'id': 'bbc', 'name': 'BBC News', 'kind': 'rss', 'url': 'https://feeds.bbci.co.uk',
         'enabled': True, 'auth_mode': 'none', 'credential_set': False, 'status': 'reachable',
         'last_checked': '2026-09-09T15:00:00Z'},
        {'id': 'api', 'name': 'Example HTTP endpoint', 'kind': 'http_api', 'url': 'https://example.test/api',
         'enabled': True, 'auth_mode': 'bearer', 'credential_set': True, 'last_error': 'Fixture check failed'}],
        'feeds': [{'id': 'top', 'connection_id': 'bbc', 'name': 'Top stories',
                   'url': 'https://feeds.bbci.co.uk/news/rss.xml', 'enabled': False,
                   'interval_minutes': 30, 'item_limit': 10, 'item_count': 10,
                   'max_active_articles': 15, 'distill_instructions': 'Highlight the main development.\nKeep uncertainty and attribution.',
                   'active_article_count': 17, 'retention_status': 'review_required', 'retention_detail': 'Two oldest articles have protected links; review their retirement.',
                   'destination_ref': 'News & Research/News & Research', 'destination_title': 'News & Research',
                   'auto_curate': True, 'auto_curate_supported': True,
                   'last_checked': '2026-09-09T15:00:00Z', 'last_source_path': 'obsidience/evidence/raw/fixture.md'}],
        'providers': [{'id': 'bbc', 'name': 'BBC News', 'kind': 'rss', 'url': 'https://feeds.bbci.co.uk',
                       'description': 'Fixture publisher descriptions and headlines.',
                       'feeds': [{'name': 'Top stories', 'url': 'https://feeds.bbci.co.uk/news/rss.xml'}]}]}

    preview_payload = {'revision': 3, 'connection_id': 'bbc', 'url': 'https://feeds.bbci.co.uk/news/rss.xml',
        'feed_title': 'BBC News', 'feed_description': 'Publisher supplied descriptions', 'feed_format': 'rss20',
        'available_count': 3, 'count_limited': False, 'checked_at': '2026-09-09T18:00:00Z', 'item_limit': 10,
        'entries': [{'position': i + 1, 'title': title, 'published': '2026-09-09T15:00:00Z',
                     'reporting_url': 'https://example.test/story-' + str(i),
                     'summary': 'This publisher description explains the actual report and is available before collection.',
                     'has_summary': True, 'has_content': False, 'selected': True}
                    for i, title in enumerate(['River observatory publishes its annual report',
                        'Community garden opens for the autumn season',
                        'New exhibition brings local history to the library'])]}

    payload['destination_nodes'] = [
        {'ref': 'News & Research/News & Research', 'title': 'News & Research', 'auto_curate': True,
         'auto_curate_supported': True, 'available': True},
        {'ref': 'Projects/Science/Science', 'title': 'Science', 'auto_curate': False,
         'auto_curate_supported': True, 'available': True},
        {'ref': 'Agents/Alexandria/Observations/Observations', 'title': 'Observations', 'auto_curate': True,
         'auto_curate_supported': True, 'available': True},
        {'ref': 'Agents/Darwin/Observations/Observations', 'title': 'Observations', 'auto_curate': False,
         'auto_curate_supported': True, 'available': True},
        {'ref': 'Games/Games', 'title': 'Unavailable Knowledge node', 'auto_curate': True,
         'auto_curate_supported': True, 'available': False}]

    items = [{'source_id': 'captured-' + str(i), 'source_path': 'obsidience/evidence/raw/fixture-' + str(i) + '.json',
              'feed_id': 'top', 'feed_name': 'Top stories', 'title': title,
              'published': '2026-09-09T15:00:00Z', 'captured_at': 1788966000,
              'reporting_url': 'https://example.test/story-' + str(i)}
             for i, title in enumerate(['River observatory publishes its annual report',
                                        'Community garden opens for the autumn season',
                                        'New exhibition brings local history to the library'])]
    content = ('This is captured provider content from the isolated reader fixture. The original reporting remains '
               'attached to its exact immutable Source.\n\n'
               'The reader uses the feed text already held by Obsidience. Selecting another item changes only '
               'the local reading selection; it does not fetch an article page or generate a summary.\n\n'
               '<img src="http://127.0.0.1:UNEXPECTED/asset"> is displayed as inert text.')

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.command, self.path))
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            if self.path == '/api/connections':
                result = payload
            elif self.path.startswith('/api/feeds/items?'):
                result = {'items': items, 'limit': 100}
            elif self.path == '/api/feeds/items/captured-0':
                result = {**items[0], 'content_text': content.replace('UNEXPECTED', str(self.server.server_port))}
            else:
                result = {'unexpected': self.path}
            self.wfile.write(json.dumps(result).encode())

        def do_POST(self):
            requests.append((self.command, self.path))
            body = json.loads(self.rfile.read(int(self.headers.get('content-length', 0))))
            assert self.path == '/api/feeds/preview'
            assert body['connection_id'] == 'bbc' and body['revision'] == 3
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(preview_payload).encode())

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    visual = json.dumps((SOURCE.parents[2] / 'components/visual').resolve().as_uri())
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'PaneDockLayout.qml').write_text('''
import QtQml
QtObject {
 property int revision: 0
 function moduleState(id) { return null }
 function isDocked(id) { return false }
 function applyRecord(record) {}
}
''')
    shutil.copy2(SOURCE.parents[2] / 'workspace/PaneModuleHeader.qml', workspace / 'PaneModuleHeader.qml')
    for source in SOURCE.parent.glob('*.qml'):
        pane = source.read_text().replace('http://127.0.0.1:8765', f'http://127.0.0.1:{server.server_port}')
        pane = pane.replace('import "../../components/visual"', 'import ' + visual)
        pane = pane.replace('import "../../workspace"', 'import ' + json.dumps(workspace.as_uri()))
        pane = pane.replace('active: root.visible', 'active: false')
        (tmp_path / source.name).write_text(pane)
    settings_source = SOURCE.parent.parent / 'settings/connections/ConnectionsSettings.qml'
    settings = settings_source.read_text().replace('http://127.0.0.1:8765', f'http://127.0.0.1:{server.server_port}')
    settings = settings.replace('import "../../../components/visual"', 'import ' + visual)
    (tmp_path / settings_source.name).write_text(settings)
    reader = (SOURCE.parent.parent / 'reader/ReaderPane.qml').read_text().replace('http://127.0.0.1:8765', f'http://127.0.0.1:{server.server_port}')
    (tmp_path / 'ReaderPane.qml').write_text(reader.replace('active: root.followShellSelection', 'active: false'))
    fixture = tmp_path / 'fixture.qml'
    fixture.write_text('''
import QtQuick
import QtQuick.Window
import "workspace"
Window {
 id: win
 width: PANE_WIDTH; height: 760; visible: true; color: "#040c12"
 PaneDockLayout { id: dock }
 FeedsPane {
  id: pane; anchors.fill: parent; dockLayout: dock; surfaceId: "samsung"
  onOpenCapturedItem: item => reader.applyShellEvent(JSON.stringify({schema:"obsidience.shell.event.v1",type:"pane.state",pane:{pane_id:"reader"},selection:{kind:"source",key:item.source_path,feed_item_id:item.source_id}}))
  onOpenPreviewItem: item => reader.applyShellEvent(JSON.stringify({schema:"obsidience.shell.event.v1",type:"pane.state",pane:{pane_id:"reader"},selection:{kind:"feed_preview",item:item}}))
 }
 ReaderPane { id: reader; anchors.fill: parent; visible: false; followShellSelection: false }
 Loader { id: settings; anchors.fill: parent; active: false; sourceComponent: ConnectionsSettings {} }
 property int stage: 0
 function findObject(item, name) {
  if (item.objectName === name) return item
  for (const child of item.children || []) { const found = findObject(child, name); if (found) return found }
  return null
 }
 function capture(item, name, next) {
  stage = -1
  item.grabToImage(result => {
   if (!result.saveToFile(IMAGE_ROOT + "/" + name + ".png")) { Qt.exit(20); return }
   next()
  })
 }
 Timer {
  interval: 100; repeat: true; running: true
  onTriggered: {
   if (stage === -1 || pane.loading || pane.connections.length !== 2) return
   const browser = findObject(pane,"feed-browser")
   if (stage === 0) {
    if (!browser || browser.loading || browser.items.length !== 3) return
    if (pane.manageMode || findObject(pane,"reader-prose")) { Qt.exit(21); return }
    capture(pane,"feeds",() => {
     if (win.width === 320) { Qt.quit(); return }
     reader.followShellSelection = true
     pane.presentCapturedItem(browser.items[0])
     pane.visible=false; reader.visible=true; stage=1
    })
   } else if (stage === 1) {
    if (reader.loading || !reader.articleBody) return
    const prose = findObject(reader,"reader-prose")
    if (!reader.feedItemMode || !prose.visible || prose.textFormat !== Text.PlainText) { Qt.exit(22); return }
    capture(reader,"captured-reader",()=> {
     reader.visible=false; pane.visible=true
     pane.openFeed("top","preview"); pane.requestPreview(); stage=2
    })
   } else if (stage === 2) {
    if (pane.previewLoading) return
    if (!pane.previewData || pane.previewError) { console.log(pane.previewError); Qt.exit(23); return }
    const second=findObject(pane,"feed-preview-item-1")
    const save=findObject(pane,"feed-save")
    if (!second || second.mapToItem(pane,0,second.height).y > save.mapToItem(pane,0,0).y-8) { Qt.exit(24); return }
    pane.draftItemLimit=1
    if (second.included) { Qt.exit(25); return }
    pane.draftItemLimit=2
    capture(pane,"publisher-preview",()=> {
     const first=findObject(pane,"feed-preview-item-0")
     first.clicked()
     pane.visible=false; reader.visible=true; stage=3
    })
   } else if (stage === 3) {
    if (reader.loading || !reader.previewMode || !reader.articleBody) return
    const prose=findObject(reader,"reader-prose")
    if (!prose.visible || prose.textFormat !== Text.PlainText || reader.documentPath || reader.autoCurateSupported) { Qt.exit(26); return }
    capture(reader,"preview-reader",()=> { reader.visible=false;pane.visible=true;pane.feedDetailTab="settings";stage=4 })
   } else if (stage === 4) {
    const permission=findObject(pane,"feed-auto-curate")
    const instructions=findObject(pane,"feed-distill-instructions")
    const limit=findObject(pane,"feed-active-limit")
    if (!permission.checked || !permission.enabled || limit.value!==15 || !instructions.text.includes("attribution")) { Qt.exit(27); return }
    instructions.text="x".repeat(501)
    if (pane.canSave || pane.draftDistillInstructions.length!==501) { Qt.exit(28); return }
    instructions.text="Keep uncertainty and attribution."
    capture(pane,"feed-settings",()=> { pane.visible=false;settings.active=true;stage=5 })
   } else if (stage === 5) {
    if (!settings.item || settings.item.loading || settings.item.connections.length!==2) return
    settings.item.selectRow("bbc")
    capture(settings,"connection-settings",()=>Qt.quit())
   }
  }
 }
 Timer { interval: 7500; running:true; onTriggered: { console.log("Fixture timeout",stage);Qt.exit(29) } }
}
'''.replace('PANE_WIDTH', str(pane_width)).replace('IMAGE_ROOT', json.dumps(str(tmp_path))))
    environment = os.environ.copy()
    environment.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', QT_QUICK_CONTROLS_STYLE='Basic', QT_FORCE_STDERR_LOGGING='1')
    try:
        result = subprocess.run([qml, str(fixture)], env=environment, capture_output=True, text=True, timeout=12)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
    assert result.returncode == 0, result.stdout + result.stderr + repr(requests)
    assert not any(error in result.stderr for error in ('ReferenceError','TypeError','Binding loop')), result.stderr
    expected = [('GET','/api/connections'), ('GET','/api/feeds/items?limit=100')]
    if pane_width != 320:
        expected += [('GET','/api/connections'), ('GET','/api/feeds/items/captured-0'), ('POST','/api/feeds/preview')]
    assert sorted(requests) == sorted(expected)
    evidence = os.environ.get('OBSIDIENCE_NATIVE_FEEDS_EVIDENCE')
    if evidence:
        destination=Path(evidence)/str(pane_width);destination.mkdir(parents=True,exist_ok=True)
        for picture in tmp_path.glob('*.png'): shutil.copy2(picture,destination/picture.name)
        (destination/'native-load.log').write_text(result.stdout+result.stderr)
