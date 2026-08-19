# BIM Assistant - Execution Plan Writer

A web-based tool to edit BIM Execution Plans (BEP) using a smart writing assistant.

## Features
- **Upload & View**: Upload `.docx` files and view them in the browser.
- **Smart Assistant**: Chat with the assistant to fill in missing details (e.g., Point Person, Schedule).
- **Auto-Edit**: The assistant can verify placeholders and apply edits to the document.
- **Download**: Save the modified document.
- **Image Handling**: The application preserves existing images in the document but does not modify or analyze them.

## Disclaimer
**Image Preservation**: This tool is designed to edit the *text content* of your BIM Execution Plan. While it is built to preserve all existing images, charts, and media in their original locations, the assistant **cannot see, analyze, or modify images**. All images will remain exactly as they were in the original document.

## Setup

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Set API Key**:
    You need a Google API Key.
    ```bash
    export GOOGLE_API_KEY="your_api_key_here"
    ```
    Or add it to a `.env` file (if you add `python-dotenv` support, currently uses system env).

3.  **Run the App**:
    ```bash
    python app.py
    ```
    Open http://localhost:5000 in your browser.

## Usage
1.  Upload your BEP document.
2.  The assistant will analyze it and suggest missing information.
3.  Chat with the assistant to provide details (e.g., "The point person is John Smith").
4.  The assistant will apply the changes.
5.  Download the updated document.

## Deployment to Vercel

The application is configured for deployment on Vercel using the `@vercel/python` runtime.

1.  **Project Root**: Ensure you are deploying from the workspace root (where `vercel.json` is located).
2.  **Environment Variables**: Add `GOOGLE_API_KEY` to your Vercel project settings.
3.  **Limitations on Vercel**:
    *   **Stateless Storage**: Vercel Serverless Functions are ephemeral. Files uploaded are stored in `/tmp`, which may not persist between requests (e.g., between the upload and the chat/edit request).
    *   **Recommendation**: For a production Vercel deployment, integrate with **Vercel Blob** or **AWS S3** to store the DOCX files persistently. The current implementation uses `/tmp` which is suitable for testing or single-instance deployments but may be unreliable under load or if the function cold-starts frequently.
