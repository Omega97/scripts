#!/usr/bin/env python3
"""
Convert a Markdown file to a professionally styled PDF.

Based on ai-feed.md (Markdown → HTML → PDF). Uses xhtml2pdf on Windows
because WeasyPrint requires system GTK/Pango libraries that are often missing.

Usage:
    md_to_pdf input.md
    md_to_pdf input.md output.pdf
    md_to_pdf input.md output.pdf --css style.css
"""
import argparse
import sys
from pathlib import Path

import markdown
from xhtml2pdf import pisa


def convert_markdown_to_pdf(md_filepath, pdf_filepath, css_filepath=None):
    """
    Converts a Markdown file into a professionally styled PDF using
    Python-Markdown and xhtml2pdf.
    """
    # 1. Read the Markdown content
    with open(md_filepath, "r", encoding="utf-8") as f:
        md_content = f.read()

    # 2. Convert Markdown to HTML (with useful extensions like tables and code highlights)
    html_body = markdown.markdown(
        md_content, extensions=["extra", "codehilite", "toc"]
    )

    # 3. Define professional default CSS styling
    default_css = """
    @page {
        size: A4;
        margin: 20mm 15mm;
        background-color: #fff9f5;
    }
    body {
        font-family: Helvetica, Arial, sans-serif;
        color: #2c3e50;
        margin: 0;
        padding: 0;
        line-height: 1.6;
    }
    h1, h2, h3 {
        color: #c0392b;
    }
    h2 {
        border-left: 4px solid #e74c3c;
        padding-left: 10px;
        margin-top: 25px;
        margin-bottom: 12px;
    }
    ul, ol {
        margin: 0 0 20px 0;
        padding-left: 20px;
    }
    li {
        margin-bottom: 8px;
    }
    code {
        background: #fdf3f2;
        padding: 2px 5px;
        font-family: Courier, monospace;
    }
    pre {
        background: #fdf3f2;
        padding: 10px;
        font-family: Courier, monospace;
    }
    """

    # Load custom CSS if provided, otherwise use default
    css_content = default_css
    if css_filepath:
        with open(css_filepath, "r", encoding="utf-8") as f:
            css_content = f.read()

    # 4. Wrap the HTML body inside a complete HTML template
    html_document = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>{css_content}</style>
    </head>
    <body>
    {html_body}
    </body>
    </html>
    """

    # 5. Render and save as PDF
    with open(pdf_filepath, "wb") as pdf_file:
        result = pisa.CreatePDF(html_document, dest=pdf_file, encoding="utf-8")
    if result.err:
        raise RuntimeError(
            f"PDF generation reported {result.err} error(s)"
        )
    print(f"Successfully generated PDF: {pdf_filepath}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Convert a Markdown file to a styled PDF."
    )
    parser.add_argument("input", help="Path to the input Markdown file")
    parser.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Path to the output PDF (default: same name as input with .pdf)",
    )
    parser.add_argument(
        "-c",
        "--css",
        default=None,
        help="Optional path to a custom CSS stylesheet",
    )
    args = parser.parse_args(argv)

    md_path = Path(args.input)
    if not md_path.is_file():
        print(f"Error: Markdown file not found: {md_path}", file=sys.stderr)
        return 1

    if args.output:
        pdf_path = Path(args.output)
    else:
        pdf_path = md_path.with_suffix(".pdf")

    if args.css:
        css_path = Path(args.css)
        if not css_path.is_file():
            print(f"Error: CSS file not found: {css_path}", file=sys.stderr)
            return 1
        css_filepath = str(css_path)
    else:
        css_filepath = None

    try:
        convert_markdown_to_pdf(str(md_path), str(pdf_path), css_filepath)
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error converting Markdown to PDF: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
