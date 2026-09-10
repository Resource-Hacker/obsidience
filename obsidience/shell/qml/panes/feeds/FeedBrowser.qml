pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components/visual"

Item {
    id: root
    property string apiBase: "http://127.0.0.1:8765"
    property var connections: []
    property var feeds: []
    property string selectedFeedId: ""
    property string selectedItemId: ""
    property var items: []
    property bool loading: false
    property bool truncated: false
    property string errorMessage: ""
    property string actionError: ""
    property int requestGeneration: 0
    readonly property bool wide: width >= 720
    readonly property var selectedFeed: feeds.find(row => row.id === selectedFeedId) || null
    readonly property var selectedItem: items.find(row => row.source_id === selectedItemId) || null
    readonly property var feedOptions: [{"id":"", "name":"All collected items"}].concat(feeds.map(feed => {
        const connection = connections.find(row => row.id === feed.connection_id)
        return {"id":feed.id, "name":(connection ? connection.name + " / " : "") + feed.name}
    }))
    readonly property var navigationRows: {
        const rows = [{"kind": "feed", "id": "", "name": "All collected items"}]
        const groups = connections.map(connection => ({"name": connection.name,
            "feeds": feeds.filter(feed => feed.connection_id === connection.id)}))
        const unassigned = feeds.filter(feed => !connections.some(connection => connection.id === feed.connection_id))
        if (unassigned.length) groups.push({"name": "Connection unavailable", "feeds": unassigned})
        for (const group of groups) {
            if (!group.feeds.length) continue
            rows.push({"kind": "group", "id": "", "name": group.name})
            for (const feed of group.feeds) rows.push({"kind": "feed", "id": feed.id, "name": feed.name})
        }
        return rows
    }
    signal openCapturedItem(var item)
    signal manageFeedRequested(string id, string tab)
    signal refreshRequested()
    signal connectionSettingsRequested()

    function itemDate(item) {
        const value = item.published || item.captured_at
        if (!value) return ""
        const date = new Date(typeof value === "number" ? value * 1000 : value)
        return isNaN(date.getTime()) ? String(value) : date.toISOString().slice(0, 10)
    }

    function destinationLabel(feed) {
        if (!feed) return ""
        if (feed.destination_error) return "Destination unavailable · " + feed.destination_error
        if (!feed.destination_ref) return "Select a Knowledge destination"
        const name = feed.destination_title || feed.destination_ref
        const permission = feed.auto_curate_supported === true && typeof feed.auto_curate === "boolean"
            ? feed.auto_curate ? "Automatic" : "Review" : "Permission unavailable"
        return name + " · " + permission
    }

    function activeArticleLabel(feed) {
        const count = Number.isInteger(feed.active_article_count) && feed.active_article_count >= 0
            ? String(feed.active_article_count) : "Not reported"
        const limit = Number.isInteger(feed.max_active_articles) ? String(feed.max_active_articles) : "Not reported"
        return "Active articles: " + count + " / " + limit
    }

    function retentionLabel(feed) {
        switch (feed.retention_status) {
        case "within_limit": return "Within limit"
        case "review_required": return "Retirement needs review"
        case "blocked": return "Retirement blocked"
        case "over_limit": return "Over article limit"
        default: return "Retention not reported"
        }
    }

    function selectFeed(id) {
        if (selectedFeedId === id && items.length) return
        selectedFeedId = id
        selectedItemId = ""
        items = []
        refresh()
    }

    function refresh() {
        const generation = ++requestGeneration
        loading = true
        errorMessage = ""
        const request = new XMLHttpRequest()
        request.open("GET", apiBase + "/api/feeds/items?limit=100"
            + (selectedFeedId ? "&feed_id=" + encodeURIComponent(selectedFeedId) : ""))
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE || !root || generation !== root.requestGeneration) return
            root.loading = false
            if (request.status < 200 || request.status >= 300) {
                root.errorMessage = "Captured items could not be loaded (HTTP " + request.status + ")."
                return
            }
            try {
                const payload = JSON.parse(request.responseText)
                if (!Array.isArray(payload.items) || payload.items.some(item => typeof item.source_id !== "string"
                        || typeof item.source_path !== "string" || typeof item.title !== "string")) throw new Error("Invalid items")
                root.items = payload.items
                root.truncated = payload.truncated === true
                if (!root.items.some(item => item.source_id === root.selectedItemId)) {
                    root.selectedItemId = root.items.length ? root.items[0].source_id : ""
                }
            } catch (error) {
                root.errorMessage = "The Harness returned invalid captured-item metadata."
            }
        }
        request.send()
    }

    onFeedsChanged: { if (selectedFeedId && !selectedFeed) selectFeed("") }
    Component.onCompleted: refresh()

    component Action: GlowButton {
        uppercase: false; textPixelSize: 12; textLetterSpacing: 0
        idleTextOpacity: 0.9; implicitHeight: 32
    }
    RowLayout {
        anchors.fill: parent; anchors.margins: 8
        spacing: 14
        ListView {
            id: feedList
            objectName: "feed-browser-sidebar"
            visible: root.wide
            Layout.preferredWidth: 200
            Layout.fillHeight: true
            clip: true
            spacing: 4
            model: root.navigationRows
            ScrollBar.vertical: ScrollBar {}
            delegate: ItemDelegate {
                id: feedRow
                required property var modelData
                width: feedList.width
                enabled: modelData.kind === "feed"
                leftPadding: 10; rightPadding: 10; topPadding: 10; bottomPadding: 10
                implicitHeight: feedTitle.implicitHeight + 20
                background: Rectangle {
                    radius: 4
                    color: feedRow.modelData.kind !== "feed" ? "transparent"
                        : root.selectedFeedId === feedRow.modelData.id ? "#173845"
                        : feedRow.hovered ? "#102934" : "transparent"
                }
                contentItem: Text {
                    id: feedTitle
                    text: feedRow.modelData.name
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: feedRow.modelData.kind === "group" ? "#7796a7" : "#d9eef5"
                    font.pixelSize: feedRow.modelData.kind === "group" ? 12 : 14
                    font.weight: feedRow.modelData.kind === "group" ? Font.DemiBold : Font.Normal
                }
                onClicked: root.selectFeed(modelData.id)
            }
        }
        Rectangle { visible: root.wide; Layout.preferredWidth: 1; Layout.fillHeight: true; color: "#263d48" }
        ColumnLayout {
        Layout.fillWidth: true; Layout.fillHeight: true
        spacing: 8
        GlowComboBox {
            objectName: "feed-browser-picker"
            visible: !root.wide
            Layout.fillWidth: true
            model: root.feedOptions; textRole: "name"
            textPixelSize: 12; textOpacity: 0.95; implicitHeight: 36
            currentIndex: root.feedOptions.findIndex(row => row.id === root.selectedFeedId)
            onActivated: index => root.selectFeed(root.feedOptions[index].id)
        }
        Text {
            Layout.fillWidth: true; visible: root.wide
            text: root.selectedFeed ? root.selectedFeed.name : "All collected items"
            textFormat: Text.PlainText; wrapMode: Text.Wrap
            color: "#d9eef5"; font.pixelSize: 17; font.weight: Font.DemiBold
        }
        Flow {
            Layout.fillWidth: true; spacing: 6
            Action { objectName: "browse-feed-preview"; text: "Preview"; enabled: root.feeds.length > 0; onClicked: root.manageFeedRequested(root.selectedFeedId || root.feeds[0].id, "preview") }
            Action { objectName: "browse-feed-settings"; text: "Settings"; enabled: root.feeds.length > 0; onClicked: root.manageFeedRequested(root.selectedFeedId || root.feeds[0].id, "settings") }
            Action { text: "New feed"; onClicked: root.manageFeedRequested("", "preview") }
            Action { text: "Refresh"; enabled: !root.loading; onClicked: root.refreshRequested() }
        }
        Text {
            Layout.fillWidth: true; visible: !!root.selectedFeed
            text: root.selectedFeed ? root.destinationLabel(root.selectedFeed) : ""
            textFormat: Text.PlainText; wrapMode: Text.Wrap
            color: root.selectedFeed && root.selectedFeed.destination_error ? "#fda4af" : "#8dacbb"
            font.pixelSize: 12
        }
        Text {
            Layout.fillWidth: true; visible: !!root.selectedFeed
            text: root.selectedFeed ? root.activeArticleLabel(root.selectedFeed) : ""
            textFormat: Text.PlainText; color: "#8dacbb"; wrapMode: Text.Wrap; font.pixelSize: 12
        }
        Text {
            Layout.fillWidth: true; visible: root.loading || !!root.errorMessage || !!root.actionError
            text: root.loading ? "Loading collected items…" : root.errorMessage || root.actionError
            textFormat: Text.PlainText; wrapMode: Text.Wrap
            color: root.errorMessage || root.actionError ? "#fda4af" : "#8dacbb"; font.pixelSize: 12
        }
        ListView {
            id: itemList
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true
            spacing: 3
            model: root.items
            ScrollBar.vertical: ScrollBar {}
            delegate: ItemDelegate {
                id: itemRow
                required property var modelData
                width: itemList.width
                implicitHeight: rowContent.implicitHeight + 18
                leftPadding: 8; rightPadding: 8; topPadding: 9; bottomPadding: 9
                background: Rectangle { radius: 4; color: root.selectedItemId === itemRow.modelData.source_id ? "#173845" : itemRow.hovered ? "#102934" : "#091923" }
                contentItem: ColumnLayout {
                    id: rowContent
                    spacing: 6
                    Text { Layout.fillWidth: true; text: itemRow.modelData.title; textFormat: Text.PlainText; color: "#d9eef5"; font.pixelSize: 14; wrapMode: Text.Wrap; maximumLineCount: 3; elide: Text.ElideRight }
                    Text { Layout.fillWidth: true; text: (root.selectedFeedId ? "" : (itemRow.modelData.feed_name || "") + " · ") + root.itemDate(itemRow.modelData); textFormat: Text.PlainText; color: "#88a8b8"; font.pixelSize: 12; elide: Text.ElideRight }
                }
                onClicked: { root.selectedItemId = modelData.source_id; root.openCapturedItem(modelData) }
            }
            Text {
                anchors.centerIn: parent; width: parent.width - 20
                visible: !root.loading && !root.errorMessage && !root.items.length
                text: "No items collected yet. Preview a feed, then collect when ready. Select an item to read it in Reader."
                textFormat: Text.PlainText; color: "#8dacbb"; font.pixelSize: 13; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter
            }
        }
        Text { Layout.fillWidth: true; text: root.items.length + (root.truncated ? "+" : "") + " collected items"; color: "#7796a7"; font.pixelSize: 11 }
        Action { visible: !root.feeds.length; text: "Connection settings"; onClicked: root.connectionSettingsRequested() }
          }
    }
}
