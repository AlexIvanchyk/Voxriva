# Documentation asset licenses

Voxriva's own documentation, screenshots and artwork use the project's
[MIT license](license.md). The generated documentation also contains the
following third-party theme, browser and icon assets. Their upstream terms
and attributions are retained below; Voxriva's MIT declaration does not
relicense them.

This inventory covers the English static site generated with Material for
MkDocs **9.7.7** and the pinned documentation toolchain. It does not cover
application images, SDK distributions or their dependencies. Those retain
the separate [artifact redistribution review](third-party.md).

| Included component | Attribution and terms | Retained text |
| --- | --- | --- |
| Material for MkDocs 9.7.7: theme, templates, CSS and JavaScript | Martin Donath; MIT | [License](assets/licenses/mkdocs-material-9.7.7-LICENSE.txt) |
| clipboard.js 2.0.11 | Zeno Rocha; MIT | [License](assets/licenses/clipboard-2.0.11-LICENSE.txt) |
| clipboard.js bundled helpers: good-listener 1.2.2, select 1.1.2, delegate 3.2.0, tiny-emitter 2.1.0 | Zeno Rocha and Scott Corgan; MIT | [good-listener notice](assets/licenses/good-listener-1.2.2-NOTICE.txt), [select notice](assets/licenses/select-1.1.2-NOTICE.txt), [delegate notice](assets/licenses/delegate-3.2.0-NOTICE.txt), [tiny-emitter license](assets/licenses/tiny-emitter-2.1.0-LICENSE.txt) |
| escape-html 1.0.3 | TJ Holowaychuk, Andreas Lubbe and Tiancheng “Timothy” Gu; MIT | [License](assets/licenses/escape-html-1.0.3-LICENSE.txt) |
| focus-visible 5.2.1 | W3C contributors; W3C Software and Document License (2015) | [Upstream notice](assets/licenses/focus-visible-5.2.1-LICENSE.txt), [full terms](assets/licenses/W3C-2015-LICENSE.txt) |
| RxJS 7.8.2 | Google, Netflix, Microsoft and contributors; Apache-2.0 | [License and attribution](assets/licenses/rxjs-7.8.2-LICENSE.txt) |
| tslib 2.7.0 | Microsoft; 0BSD | [License](assets/licenses/tslib-2.7.0-LICENSE.txt) |
| Lunr 2.3.9: English search in the bundled worker | Oliver Nightingale; MIT | [License](assets/licenses/lunr-2.3.9-LICENSE.txt) |
| material-design-color 2.3.2: CSS color definitions | Denis Malinochkin; MIT | [License](assets/licenses/material-design-color-2.3.2-LICENSE.txt) |
| Material Design Icons packaged with the theme | [Pictogrammers](https://pictogrammers.com/); collection notice identifies Apache-2.0 for icons | [Collection notice](assets/licenses/material-icons-LICENSE.txt), [Apache-2.0 terms](assets/licenses/rxjs-7.8.2-LICENSE.txt) |
| Font Awesome Free SVG icons packaged with the theme | [Fonticons, Inc.](https://fontawesome.com/); CC-BY-4.0 for icons | [License and attribution](assets/licenses/fontawesome-LICENSE.txt) |

Theme JavaScript and CSS are the prebuilt upstream bundles. This project
does not edit their runtime source. Inline icons are supplied by the theme;
Voxriva does not claim ownership of those icons or their trademarks.
Web fonts are disabled. Search is configured for English; unused additional
language, TinySegmenter and Wordcut files are excluded from this static site.

The [provenance record](assets/licenses/provenance.json) identifies the
installed theme files, exact upstream npm archives, archive integrity values
and retained notice checksums. JavaScript sources present in the theme's
source maps were compared with the corresponding locked npm packages.
The original copyright and license statements remain in those source maps.
Recheck the inventory when updating the theme, enabling another search
language, adding fonts or introducing other browser assets. This bounded
asset inventory is not a complete legal audit of every Voxriva distribution.
