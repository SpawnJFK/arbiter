"""Programmatic fixtures for IDML, subtitles, XML, DITA, app resources, YAML and AsciiDoc.

All content is fictional (a kettle app). No binaries are checked in: the IDML package
is assembled here so the tests control exactly which constructs appear.
"""

from __future__ import annotations

import io
import zipfile

# --------------------------------------------------------------------------- IDML

IDPKG = "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"
_PLAIN = 'AppliedCharacterStyle="CharacterStyle/$ID/[No character style]"'
_BOLD = 'AppliedCharacterStyle="CharacterStyle/$ID/[No character style]" FontStyle="Bold"'
_EMPH = 'AppliedCharacterStyle="CharacterStyle/Emphasis"'


def _csr(attrs: str, inner: str) -> str:
    return f"<CharacterStyleRange {attrs}>{inner}</CharacterStyleRange>"


def _psr(style: str, inner: str) -> str:
    return (
        f'<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/{style}">{inner}</ParagraphStyleRange>'
    )


def _story(self_id: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<idPkg:Story xmlns:idPkg="{IDPKG}" DOMVersion="18.0">\n'
        f'<Story Self="{self_id}" AppliedTOCStyle="n" TrackChanges="false">'
        '<StoryPreference OpticalMarginAlignment="false"/>'
        f"{body}</Story>\n</idPkg:Story>\n"
    )


STORY_MAIN = _story(
    "u100",
    _psr("Heading 1", _csr(_PLAIN, "<Content>Kettle Guide</Content><Br/>"))
    + _psr(
        "$ID/NormalParagraphStyle",
        # One paragraph over three runs; the bold run splits the base formatting.
        _csr(_PLAIN, "<Content>Fill the kettle with </Content>")
        + _csr(_BOLD, "<Content>cold</Content>")
        + _csr(
            _PLAIN,
            "<Content> water. Then press the switch.</Content><Br/>"
            # Second paragraph starts inside the same run.
            "<Content>Visit </Content>"
            '<HyperlinkTextSource Self="hts1" Name="Site" Hidden="false"><Content>our site</Content>'
            "</HyperlinkTextSource>"
            "<Content> for help.<?ACE 7?>Tip inside.</Content><Br/>",
        )
        + _csr(
            _PLAIN,
            "<Content>See note</Content>"
            '<Note Collapsed="false"><ParagraphStyleRange><CharacterStyleRange>'
            "<Content>Editor: check wording</Content></CharacterStyleRange></ParagraphStyleRange></Note>"
            '<Footnote><ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Footnote">'
            "<CharacterStyleRange><Content><?ACE 4?> Tested in a fictional lab.</Content>"
            "</CharacterStyleRange></ParagraphStyleRange></Footnote>"
            "<Content> and the </Content>",
        )
        + _csr(_EMPH, "<Content>safety</Content>")
        + _csr(_PLAIN, "<Content> rules.</Content><Br/>")
        + _csr(
            _PLAIN,
            '<Table Self="t1" BodyRowCount="1" ColumnCount="2">'
            '<Cell Self="t1i0" Name="0:0"><ParagraphStyleRange><CharacterStyleRange>'
            "<Content>Capacity</Content></CharacterStyleRange></ParagraphStyleRange></Cell>"
            '<Cell Self="t1i1" Name="1:0"><ParagraphStyleRange><CharacterStyleRange>'
            "<Content>1.7 litres</Content></CharacterStyleRange></ParagraphStyleRange></Cell>"
            "</Table><Br/>",
        )
        + _csr(_PLAIN, "<Content>2024</Content>"),
    ),
)

STORY_SIDE = _story(
    "u200",
    _psr(
        "$ID/NormalParagraphStyle",
        _csr(_PLAIN, '<HyperlinkTextDestination Self="d1" Name="top"/><Content>Side panel text.</Content>'),
    ),
)

TRACKED_STORY = _story(
    "u300",
    _psr(
        "$ID/NormalParagraphStyle",
        _csr(
            _PLAIN, '<Content>Old </Content><Change ChangeType="InsertedText"><Content>new</Content></Change>'
        ),
    ),
)


def make_idml(stories: dict[str, str] | None = None) -> bytes:
    stories = stories or {"Stories/Story_u100.xml": STORY_MAIN, "Stories/Story_u200.xml": STORY_SIDE}
    refs = "".join(f'<idPkg:Story src="{name}"/>' for name in stories)
    designmap = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<?aid style="50" type="document" readerVersion="6.0" featureSet="257"?>\n'
        f'<Document xmlns:idPkg="{IDPKG}" DOMVersion="18.0" Self="d">{refs}</Document>\n'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), b"application/vnd.adobe.indesign-idml-package")
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0" encoding="UTF-8"?><container><rootfiles>'
            '<rootfile full-path="designmap.xml"/></rootfiles></container>',
            zipfile.ZIP_DEFLATED,
        )
        z.writestr("designmap.xml", designmap, zipfile.ZIP_DEFLATED)
        for name, xml in stories.items():
            z.writestr(name, xml, zipfile.ZIP_DEFLATED)
    return buf.getvalue()


# --------------------------------------------------------------------------- subtitles

SRT = (
    "1\r\n"
    "00:00:01,000 --> 00:00:03,500\r\n"
    "Welcome to the <i>kettle</i> tutorial.\r\n"
    "\r\n"
    "2\r\n"
    "00:00:04,000 --> 00:00:07,250 X1:10 X2:100 Y1:10 Y2:50\r\n"
    "{\\an8}Fill it with water,\r\n"
    "then press <b>start</b>.\r\n"
    "\r\n"
    "3\r\n"
    "00:00:08,000 --> 00:00:09,000\r\n"
    '<font color="#ffcc00">Done!</font>\r\n'
    "\r\n"
    "4\r\n"
    "00:00:10,000 --> 00:00:11,000\r\n"
    "123\r\n"
)

VTT = """WEBVTT - Kettle tutorial
Kind: captions

STYLE
::cue { color: yellow; }

NOTE This note is for editors only.

intro
00:00:01.000 --> 00:00:03.500 align:start position:10%
<v Ana>Welcome to the <c.highlight>kettle</c> tutorial.</v>

00:00:04.000 --> 00:00:07.000 line:85%
<v.loud Ben>Fill it with water &amp; wait
<00:00:05.500>until it <i>clicks</i>.

00:01:00.000 --> 00:01:02.000
Tom &lt;3 tea
"""

ASS = """[Script Info]
Title: Kettle tutorial
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, Bold, Italic
Style: Default,Arial,20,&H00FFFFFF,0,0

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.50,Default,Ana,0,0,0,,Welcome to the {\\i1}kettle{\\i0} tutorial.
Comment: 0,0:00:02.00,0:00:03.00,Default,,0,0,0,,Editor comment, not shown
Dialogue: 0,0:00:04.00,0:00:07.00,Default,Ben,0,0,0,,{\\pos(10,20)}Fill it with water,\\Nthen wait.
Dialogue: 0,0:00:08.00,0:00:09.00,Default,,0,0,0,,Text, with a comma.
"""

# --------------------------------------------------------------------------- XML and DITA

XML_DOC = b"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Product manual, fictional -->
<manual xmlns:its="http://www.w3.org/2005/11/its" its:version="2.0" xml:lang="en">
  <its:rules version="2.0">
    <its:translateRule selector="//sku" translate="no"/>
    <its:translateRule selector="//figure/@caption" translate="yes"/>
    <its:withinTextRule selector="//term" withinText="yes"/>
    <its:locNoteRule selector="//warning" locNotePointer="no"><its:locNote>Legal text, keep the tone.</its:locNote></its:locNoteRule>
  </its:rules>
  <title>Getting started</title>
  <section id="s1">
    <para>Press the <em>red</em> button. Then wait <ref target="x"/> seconds.</para>
    <para its:translate="no">Do not translate this.</para>
    <para its:locNote="Keep it short">Model <sku>AB-12</sku> is new &amp; improved.</para>
    <list><item><term>Boil</term></item></list>
    <figure caption="A blue kettle" alt="Kettle photo" src="k.png" id="fig1"/>
    <code>print(1)</code>
    <warning>Do not touch the <!-- hot --> lid.</warning>
    <meta><keywords>kettle, water</keywords></meta>
  </section>
</manual>
"""

DITA_TASK = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE task PUBLIC "-//OASIS//DTD DITA Task//EN" "task.dtd">
<task id="install" xml:lang="en-US">
  <title>Installing the <keyword>Kettle</keyword> app</title>
  <shortdesc>How to install the app on your phone.</shortdesc>
  <taskbody>
    <steps>
      <step><cmd>Open <uicontrol>Settings</uicontrol> and run <codeph>kettle --install</codeph>.</cmd>
        <info><p>This takes a minute.<fn>Depends on your network.</fn></p></info></step>
    </steps>
    <result><p translate="no">INTERNAL-ONLY</p><draft-comment>Check the wording</draft-comment>
      <codeblock>sudo apt install kettle</codeblock>
      <p>Done. <image href="ok.png"><alt>Success icon</alt></image></p></result>
  </taskbody>
</task>
"""

DITAMAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE map PUBLIC "-//OASIS//DTD DITA Map//EN" "map.dtd">
<map xml:lang="en">
  <title>Kettle user guide</title>
  <topicref href="install.dita" navtitle="Installing the app">
    <topicmeta><navtitle>Install</navtitle><shortdesc>Set up in minutes.</shortdesc></topicmeta>
  </topicref>
  <topicref href="clean.dita" format="dita"/>
</map>
"""

ANDROID = b"""<?xml version="1.0" encoding="utf-8"?>
<resources xmlns:xliff="urn:oasis:names:tc:xliff:document:1.2" xmlns:tools="http://schemas.android.com/tools">
    <string name="app_name" translatable="false">Kettle</string>
    <!-- Greeting on the home screen -->
    <string name="welcome">Welcome, <xliff:g id="name" example="Ana">%1$s</xliff:g>! You\\'re in.</string>
    <string name="multi">Line one\\nLine two with <b>bold</b> &amp; \\"quotes\\"</string>
    <string name="at_sign">\\@ mentions are on</string>
    <string name="cdata"><![CDATA[Tap <b>here</b> now]]></string>
    <string-array name="modes">
        <item>Boil</item>
        <item>Keep warm</item>
    </string-array>
    <string-array name="codes" translatable="false"><item>AB</item></string-array>
    <plurals name="cups">
        <item quantity="one">%d cup</item>
        <item quantity="other">%d cups</item>
    </plurals>
    <integer name="max_cups">8</integer>
</resources>
"""

# --------------------------------------------------------------------------- app resources

ARB = """{
  "@@locale": "en",
  "appTitle": "Kettle",
  "@appTitle": {
    "description": "Title of the application"
  },
  "greeting": "Hello {name}!",
  "@greeting": {
    "description": "Greeting on the home screen",
    "placeholders": {"name": {"type": "String", "example": "Ana"}}
  },
  "cups": "{count, plural, =0{No cups} one{One cup} other{{count} cups}}",
  "icon": "assets/kettle.png"
}
"""

IOS_STRINGS = """/* Title of the main screen */
"main.title" = "Kettle";

// Button that starts boiling
"button.start" = "Start boiling";
"greeting" = "Hello, %@! You have %1$d cups.";
"multiline" = "Line one\\nLine \\"two\\"";
legacyKey = "Bare key works";
"number" = "42";
"""

STRINGSDICT = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>cups_left</key>
    <dict>
        <key>NSStringLocalizedFormatKey</key>
        <string>You have %#@cups@ left</string>
        <key>cups</key>
        <dict>
            <key>NSStringFormatSpecTypeKey</key>
            <string>NSStringPluralRuleType</string>
            <key>NSStringFormatValueTypeKey</key>
            <string>d</string>
            <key>one</key>
            <string>%d cup</string>
            <key>other</key>
            <string>%d cups</string>
        </dict>
    </dict>
</dict>
</plist>
"""

PROPERTIES = (
    "# Kettle app messages\n"
    "app.title=Kettle\n"
    "\n"
    "! Shown on the start screen\n"
    "greeting = Hello {0}, welcome back!\n"
    "long.text = This is a long text \\\n"
    "    that continues on the next line.\n"
    "colon.key: Caf\\u00e9 is open\n"
    "space.key Water\\tTea\\nCoffee\n"
    "path=C\\:\\\\kettle\n"
    "empty=\n"
    "number=42\n"
)

RESX = b"""<?xml version="1.0" encoding="utf-8"?>
<root>
  <resheader name="resmimetype"><value>text/microsoft-resx</value></resheader>
  <data name="Greeting" xml:space="preserve">
    <value>Hello {0}, you have {1:N0} cups.</value>
    <comment>Shown on the home screen</comment>
  </data>
  <data name="Title" xml:space="preserve"><value>Kettle settings</value></data>
  <data name="Icon" type="System.Resources.ResXFileRef, System.Windows.Forms"><value>icon.png;System.Drawing.Bitmap</value></data>
  <data name="&gt;&gt;button1.Name" xml:space="preserve"><value>button1</value></data>
</root>
"""

YAML_DOC = """# Rails style locale file
en:
  app:
    title: Kettle   # product name
    greeting: "Hello, %{name}!"
    quoted: 'It''s ready'
    count: 3
    enabled: true
    url: https://example.com/help
  defaults: &defaults
    tip: Pour slowly
  copy:
    <<: *defaults
    other: *defaults
  steps:
    - Fill the kettle
    - "Press: start"
  literal: |
    First line.
    Second line.
  folded: >-
    A folded paragraph
    on two lines.
  flow: {short: Boil now, long: [Keep warm, Cool down]}
"""

YAML_MULTI = """---
title: First document
---
title: Second document
"""

ASCIIDOC = """= Kettle User Guide
:author: Example Author
:toc:

== Getting *started*

Fill the kettle with _cold_ water.
Then press the `start` button.
See link:https://example.com/help[the help page] for {product} details.

// A comment that is never translated

.Safety first
NOTE: Never open the lid while boiling.

* First item with <<sec-a,a cross reference>>
* Second item +
continued here

Term one:: Definition of the term.

[source,python]
----
print("not translated")
----

|===
|Name |Capacity
|Kettle |1.7 litres
|===

  An indented literal paragraph.

____
A quoted sentence.
____
"""
