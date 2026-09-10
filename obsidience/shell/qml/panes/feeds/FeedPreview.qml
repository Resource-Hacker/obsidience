pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root

    property var previewData: null
    property int itemLimit: 10
    property bool loading: false
    property string errorMessage: ""
    signal openPreviewItem(var item)
    spacing: 12

    function itemDate(value) {
        if (!value) return "Date not supplied"
        const date = new Date(typeof value === "number" ? value * 1000 : value)
        return isNaN(date.getTime()) ? String(value) : Qt.formatDateTime(date, "d MMM yyyy")
    }

    component Copy: Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: "#93aebd"
        font.pixelSize: 13
        lineHeight: 1.2
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: emptyCopy.implicitHeight + 32
        visible: !root.previewData
        radius: 6
        color: "#0b1b26"
        Text {
            id: emptyCopy
            anchors.fill: parent; anchors.margins: 16
            text: root.errorMessage || (root.loading ? "Reading the publisher feed…"
                : "Preview the feed to see its latest headlines, dates and supplied text before choosing how much to collect.")
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: root.errorMessage ? "#fda4af" : "#a8c1ce"
            font.pixelSize: 14
            lineHeight: 1.25
        }
    }
    ColumnLayout {
        Layout.fillWidth: true
        visible: !!root.previewData
        spacing: 6
        Copy {
            objectName: "feed-preview-count"
            text: root.previewData ? (root.previewData.count_limited ? "At least " : "")
                + root.previewData.available_count + " items offered · Showing " + root.previewData.entries.length
                + " · Up to " + Math.min(root.itemLimit, root.previewData.entries.length) + " will be checked" : ""
            color: "#7dd3e8"
        }
        Copy { text: root.previewData ? "Publisher order · Previewed " + root.itemDate(root.previewData.checked_at) : ""; font.pixelSize: 12 }
        Copy { visible: !!root.previewData && !!root.previewData.entry_error; text: root.previewData ? root.previewData.entry_error || "" : ""; color: "#f5cf89" }
        Copy { visible: !!root.previewData && root.previewData.available_count === 0; text: "This publisher currently offers no items." }
    }
    Repeater {
        model: root.previewData ? root.previewData.entries : []
        delegate: ItemDelegate {
            id: entry
            required property var modelData
            required property int index
            objectName: "feed-preview-item-" + index
            readonly property bool included: index < root.itemLimit
            Layout.fillWidth: true
            implicitHeight: entryContent.implicitHeight + 24
            leftPadding: 14; rightPadding: 14; topPadding: 12; bottomPadding: 12
            background: Rectangle {
                radius: 6
                color: entry.included ? entry.hovered ? "#173a47" : "#102a36" : entry.hovered ? "#12232e" : "#0a1822"
                border.color: entry.included ? "#2a6275" : "#233540"
            }
            contentItem: ColumnLayout {
                id: entryContent
                spacing: 6
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: String(entry.index + 1).padStart(2, "0"); color: entry.included ? "#82d9e9" : "#6d8998"; font.pixelSize: 12; font.weight: Font.DemiBold }
                    Text { Layout.fillWidth: true; text: entry.included ? "Will check" : "Outside amount"; color: entry.included ? "#82d9e9" : "#6d8998"; font.pixelSize: 12 }
                    Text { text: root.itemDate(entry.modelData.published); textFormat: Text.PlainText; color: "#93aebd"; font.pixelSize: 12 }
                }
                Text {
                    Layout.fillWidth: true
                    text: entry.modelData.title
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: "#e0edf3"
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    lineHeight: 1.15
                }
                Text {
                    Layout.fillWidth: true
                    visible: text.length > 0
                    text: entry.modelData.summary
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    maximumLineCount: 1
                    elide: Text.ElideRight
                    color: "#a5bcc9"
                    font.pixelSize: 14
                    lineHeight: 1.25
                }
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: entry.modelData.has_content ? "Publisher content available" : entry.modelData.has_summary ? "Publisher summary" : entry.modelData.reporting_url ? "Link only" : "Title only"
                        color: "#7396a9"; font.pixelSize: 12
                    }
                    Text { text: "Read  ›"; color: "#8fc5d6"; font.pixelSize: 12 }
                }
            }
            onClicked: root.openPreviewItem(Object.assign({}, modelData, {
                "feed_title": root.previewData.feed_title || "", "feed_url": root.previewData.url || ""}))
        }
    }
}
