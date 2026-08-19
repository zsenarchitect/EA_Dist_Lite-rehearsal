import traceback
import json
import os
import win32com.client
import io
import time
import _Exe_Util

# COM error codes when dispatching Outlook
COM_E_INVALID_CLASS = -2147221005   # Invalid class string (Outlook not installed/registered)
COM_E_UNAVAILABLE = -2147221021     # Operation unavailable (e.g. no running Outlook, wrong session)
COM_E_SERVER_EXEC_FAILED = -2146959355  # Server execution failed (Outlook stuck, modal dialog, etc.)


def _get_com_error_code(e):
    """Get COM HRESULT from exception (pywintypes.com_error has args[0] = hresult)."""
    if hasattr(e, 'args') and e.args:
        return e.args[0]
    return getattr(e, 'hresult', None)


def try_dispatch_outlook(max_retries=3, retry_delay=2):
    """
    Attempt to dispatch Outlook with retry logic.
    
    Args:
        max_retries: Maximum number of retry attempts
        retry_delay: Delay in seconds between retries
        
    Returns:
        Outlook Application object if successful
        
    Raises:
        RuntimeError: If all retry attempts fail
    """
    for attempt in range(max_retries):
        try:
            outlook = win32com.client.Dispatch("Outlook.Application")
            return outlook
        except Exception as e:
            error_code = _get_com_error_code(e)
            
            # -2147221005 = Invalid class string (COM not registered)
            if error_code == COM_E_INVALID_CLASS:
                error_msg = (
                    "Outlook COM object not available. This could mean:\n"
                    "  1. Outlook is not installed\n"
                    "  2. Outlook is not properly registered\n"
                    "  3. Office installation is corrupted\n\n"
                    "To fix:\n"
                    "  - Ensure Microsoft Outlook is installed\n"
                    "  - Try repairing Office installation\n"
                    "  - Contact IT support if issue persists"
                )
                print(error_msg)
                raise RuntimeError(error_msg)
            
            # -2147221021 = Operation unavailable (Outlook not running or wrong session)
            if error_code == COM_E_UNAVAILABLE:
                error_msg = (
                    "Outlook is not available (Operation unavailable).\n"
                    "  - Start Microsoft Outlook manually, then run this again.\n"
                    "  - If running from Task Scheduler or a service, run only when user is logged on.\n"
                    "  - If you see an Outlook security prompt, click Allow and retry."
                )
                print(error_msg)
                raise RuntimeError(error_msg)
            
            # -2146959355 = Server execution failed (Outlook stuck, modal dialog, etc.)
            if error_code == COM_E_SERVER_EXEC_FAILED:
                error_msg = (
                    "Outlook could not be used (Server execution failed).\n"
                    "  - Close any Outlook windows or dialogs (e.g. 'Allow/Block' prompts).\n"
                    "  - Quit Outlook from the system tray and start it again, then retry.\n"
                    "  - If a modal dialog is open in Outlook, close it and retry."
                )
                print(error_msg)
                raise RuntimeError(error_msg)
            
            # For other COM errors, retry
            if attempt < max_retries - 1:
                print(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                error_msg = (
                    f"Failed to initialize Outlook after {max_retries} attempts.\n"
                    f"Last error: {e}\n"
                    "  - Start Outlook manually and ensure no modal dialogs are open, then try again."
                )
                print(error_msg)
                raise RuntimeError(error_msg)
    
    raise RuntimeError("Unexpected error in try_dispatch_outlook")


def _save_email_draft_fallback(data_file_path, receiver_email_list, subject, body, body_folder_link_list,
                               body_image_link_list, attachment_list, logo_image_path):
    """
    Save email content to a draft file when Outlook COM fails, so the user can send manually.
    Writes to dump folder: failed_email_draft.html and failed_email_draft_meta.json.
    """
    try:
        dump_dir = os.path.dirname(data_file_path)
        html_path = os.path.join(dump_dir, "failed_email_draft.html")
        meta_path = os.path.join(dump_dir, "failed_email_draft_meta.json")
        full_body = body or ""
        if body_folder_link_list:
            for link in body_folder_link_list:
                full_body += '<br><br><a href="{0}">Click here to access the folder: {0}</a>'.format(link)
        if body_image_link_list:
            for link in body_image_link_list:
                full_body += '<br><br><img src="{0}"><br><br>'.format(link)
        if logo_image_path:
            full_body += '<br><br><img src="{0}"><br><br>'.format(logo_image_path)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html><html><body>")
            f.write(full_body)
            f.write("</body></html>")
        meta = {
            "To": receiver_email_list,
            "Subject": subject,
            "attachment_list": attachment_list or [],
            "instructions": "Open failed_email_draft.html to copy the body. Send manually from Outlook with the above To/Subject and attach the listed files if any."
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        print("Email draft saved (Outlook failed):\n  Body: {}\n  Meta: {}".format(html_path, meta_path))
        return html_path, meta_path
    except Exception as e:
        print("Could not save email draft: {}".format(e))
        return None, None


@_Exe_Util.try_catch_error
def send_email():
    """
    Sends an email using Outlook based on data from a JSON file.
    
    The JSON file should contain:
    - receiver_email_list: List of email addresses
    - subject: Email subject
    - body: Email body content
    - body_folder_link_list: List of folder links to include
    - body_image_link_list: List of image links to include
    - attachment_list: List of file paths to attach
    - logo_image_path: Optional path to logo image
    """
    file_name = "email_data"
    data_file_path = _Exe_Util.get_file_in_dump_folder(file_name)
    
    data = _Exe_Util.get_data(file_name)
    if not data:
        print("No email data found")
        return

    # Format recipient email list
    receiver_email_list = "; ".join(data["receiver_email_list"])
    
    # Extract email components
    subject = data["subject"]
    body = data["body"]
    body_folder_link_list = data["body_folder_link_list"]
    body_image_link_list = data["body_image_link_list"]
    attachment_list = data["attachment_list"]
    logo_image_path = data.get("logo_image_path")

    try:
        # Create Outlook message with retry logic
        outlook = try_dispatch_outlook(max_retries=3, retry_delay=2)
        message = outlook.CreateItem(0)
        message.To = receiver_email_list
        message.Subject = subject
        message.HTMLBody = body

        # Add folder links to email body
        if body_folder_link_list:
            for link in body_folder_link_list:
                message.HTMLBody += '<br><br><a href="{0}">Click here to access the folder: {0}</a>'.format(link)

        # Add image links to email body
        if body_image_link_list:
            for link in body_image_link_list:
                message.HTMLBody += '<br><br><img src="{0}"><br><br>'.format(link)

        # Add logo image if provided
        if logo_image_path:
            message.HTMLBody += '<br><br><img src="{0}"><br><br>'.format(logo_image_path)

        # Add attachments
        if attachment_list:
            for file in attachment_list:
                message.Attachments.Add(file, 1)

        # Send the email
        message.Send()
    except (RuntimeError, Exception) as e:
        # When Outlook COM fails, save draft so user can send manually
        code = _get_com_error_code(e)
        if isinstance(e, RuntimeError) or code in (COM_E_UNAVAILABLE, COM_E_SERVER_EXEC_FAILED, COM_E_INVALID_CLASS):
            _save_email_draft_fallback(
                data_file_path, receiver_email_list, subject, body,
                body_folder_link_list, body_image_link_list, attachment_list, logo_image_path
            )
        raise

    # Clean up the data file
    try:
        if os.path.exists(data_file_path):
            os.remove(data_file_path)
    except Exception as cleanup_error:
        print("Warning: Could not remove data file: {0}".format(cleanup_error))
    
    print("Email sent successfully")


if __name__ == "__main__":
    send_email()


