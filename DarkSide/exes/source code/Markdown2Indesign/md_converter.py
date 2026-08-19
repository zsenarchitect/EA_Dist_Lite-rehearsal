import os
import re
import subprocess
import time
import logging
import threading
# Set up logging configuration at the top of the file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class MarkdownConverter:
    def __init__(self):
        self.indesign_script = """
try {
    // Tell InDesign to stop being so metric-curious
    app.scriptPreferences.measurementUnit = MeasurementUnits.INCHES;
    
    // Create a new document
    var doc = app.documents.add();
    
    // Set document preferences (already in inches, but now we're extra sure!)
    doc.viewPreferences.horizontalMeasurementUnits = MeasurementUnits.INCHES;
    doc.viewPreferences.verticalMeasurementUnits = MeasurementUnits.INCHES;
    doc.documentPreferences.pageHeight = "11in";
    doc.documentPreferences.pageWidth = "8.5in";
    doc.documentPreferences.facingPages = true;
    
    // Set margins with different left/right margins for facing pages
    doc.marginPreferences.top = "0.75in";
    doc.marginPreferences.bottom = "0.75in";

    
    // Add variables for inside/outside margins
    var insideMargin = 1    ;  // inches
    var outsideMargin = 0.75; // inches
    
    // Update margin preferences using these variables
    doc.marginPreferences.left = insideMargin + "in";
    doc.marginPreferences.right = outsideMargin + "in";
    
    // Create paragraph styles
    var styleH1 = doc.paragraphStyles.add({name: "Heading 1"});
    styleH1.properties = {
        pointSize: "24pt",
        fontStyle: "Bold",
        spaceBefore: "24pt",
        spaceAfter: "12pt"
    };
    
    var styleH2 = doc.paragraphStyles.add({name: "Heading 2"});
    styleH2.properties = {
        pointSize: "20pt",
        fontStyle: "Bold",
        spaceBefore: "18pt",
        spaceAfter: "9pt"
    };
    
    var styleH3 = doc.paragraphStyles.add({name: "Heading 3"});
    styleH3.properties = {
        pointSize: "16pt",
        fontStyle: "Bold",
        spaceBefore: "14pt",
        spaceAfter: "7pt"
    };
    
    var styleBody = doc.paragraphStyles.add({name: "Body"});
    styleBody.properties = {
        pointSize: "12pt",
        leading: "14pt",
        spaceBefore: "0pt",
        spaceAfter: "9pt"
    };
    
    var styleCode = doc.paragraphStyles.add({name: "Code"});
    styleCode.properties = {
        fontFamily: "Courier New",
        pointSize: "10pt",
        leading: "12pt",
        spaceBefore: "9pt",
        spaceAfter: "9pt"
    };
    
    // Load segments data
    var segmentsFile = File("%SEGMENTS_PATH%");
    segmentsFile.open("r");
    var fileContent = segmentsFile.read();
    segmentsFile.close();
    
    // Add an extra page at the beginning and remove its master
    doc.pages[0].appliedMaster = null;
    var currentPage = doc.pages.add();
    currentPage.appliedMaster = null;
    
    // Split into segments
    var segments = fileContent.split("\\n");
    var currentSegment = [];
    var currentType = null;
    var yPosition = doc.marginPreferences.top;
    var waitTime = 520;
    
    function getGeometricBounds(currentPage, yPosition, insideMargin, outsideMargin) {
        return [
            yPosition,  // Top
            currentPage.side == PageSideOptions.LEFT_HAND ? 
                outsideMargin : doc.documentPreferences.pageWidth + insideMargin,  // Left
            doc.documentPreferences.pageHeight - doc.marginPreferences.bottom,  // Bottom
            currentPage.side == PageSideOptions.LEFT_HAND ? 
                doc.documentPreferences.pageWidth - insideMargin : 
                doc.documentPreferences.pageWidth + doc.documentPreferences.pageWidth - outsideMargin  // Right
        ];
    }
    
    for(var i = 0; i < segments.length; i++) {
        var line = segments[i];
        
        if(line === "TEXT") {
            currentType = "text";
            currentSegment = [];
        }
        else if(line === "IMAGE") {
            currentType = "image";
            currentSegment = [];
        }
        else if(line === "ENDTEXT" || line === "ENDIMAGE") {
            // Process complete segment
            if(currentType === "text") {
                // Create text frame
                var textFrame = currentPage.textFrames.add({
                    geometricBounds: getGeometricBounds(
                        currentPage, 
                        yPosition, 
                        insideMargin, 
                        outsideMargin
                    )
                });
                
                // Fix: Properly join array and trim whitespace
                var content = currentSegment.join("\\n");
                content = content.replace(/^\\s+|\\s+$/g, "");  // JavaScript's trim equivalent
                textFrame.contents = content;
                
                
                // Apply styles
                var story = textFrame.parentStory;
                for(var j = 0; j < story.paragraphs.length; j++) {
                    var para = story.paragraphs[j];
                    var content = para.contents;
                    
                    if(content.match(/^# /)) {
                        para.appliedParagraphStyle = styleH1;
                        para.contents = content.replace(/^# /, "");
                    }
                    else if(content.match(/^## /)) {
                        para.appliedParagraphStyle = styleH2;
                        para.contents = content.replace(/^## /, "");
                    }
                    else if(content.match(/^### /)) {
                        para.appliedParagraphStyle = styleH3;
                        para.contents = content.replace(/^### /, "");
                    }
                    else if(content.match(/^```/)) {
                        para.appliedParagraphStyle = styleCode;
                        para.contents = content.replace(/^```\\w*\\n/, "").replace(/```$/, "");
                    }
                    else {
                        para.appliedParagraphStyle = styleBody;
                    }
                }
                
                // Add a 0.5 second wait for InDesign to process
                $.sleep(waitTime);

                // Keep processing text frames until no overflow
                while (true) {
                    // Fit frame to content
                    textFrame.fit(FitOptions.FRAME_TO_CONTENT);

                    // Force bottom of text frame within margin
                    if (textFrame.geometricBounds[2] > doc.documentPreferences.pageHeight - doc.marginPreferences.bottom) {
                        textFrame.geometricBounds[2] = doc.documentPreferences.pageHeight - doc.marginPreferences.bottom;
                    }

                    // If no overflow, we're done
                    if (!textFrame.overflows) {
                        break;
                    }

                    // Create new page and text frame for overflow
                    currentPage = doc.pages.add();
                    currentPage.appliedMaster = null;
                    yPosition = doc.marginPreferences.top;
                    
                    newTextFrame = currentPage.textFrames.add({
                        geometricBounds: getGeometricBounds(
                        currentPage, 
                        yPosition, 
                        insideMargin, 
                        outsideMargin
                    )
                    })

                    // Connect the frames using nextTextFrame
                    textFrame.nextTextFrame = newTextFrame;
                    $.sleep(waitTime);
                    textFrame = newTextFrame;
                }
                
                yPosition = textFrame.geometricBounds[2] + 0.5;
                
                // Explanation: The +0.5 is added to the yPosition to create a gap between the text frames.
            }
            else if(currentType === "image") {
                var imagePath = currentSegment[0];

                // calcuate the image height in ratio to width, the width is the page width - inside margin - outside margin
                var imageWidth = doc.documentPreferences.pageWidth - insideMargin - outsideMargin;
                var imageHeight = imageWidth * (imagePath.height / imagePath.width);
                
                // Check if we need a new page
                if(yPosition > doc.documentPreferences.pageHeight - doc.marginPreferences.bottom - imageHeight) {
                    currentPage = doc.pages.add();
                    currentPage.appliedMaster = null;  // Remove master from new page
                    yPosition = doc.marginPreferences.top;
                }
                
                // Place image
                var imageFrame = currentPage.rectangles.add({
                    geometricBounds: getGeometricBounds(
                        currentPage, 
                        yPosition, 
                        insideMargin, 
                        outsideMargin
                    )
                });
                
                // Create a File object explicitly before placing
                var imageFile = new File(imagePath);
                if (!imageFile.exists) {
                    alert("Warning: Image file not found: " + imagePath);
                    continue;
                }
                
                try {
                    imageFrame.place(imageFile);
                    imageFrame.fit(FitOptions.PROPORTIONALLY);
                    imageFrame.fit(FitOptions.FRAME_TO_CONTENT);
                    
                    // Add a 0.5 second wait for InDesign to process
                    $.sleep(waitTime);
                } catch(err) {
                    alert("Warning: Could not place image: " + imagePath + "\\nError: " + err);
                    imageFrame.remove();
                    continue;
                }
                
                // Center if needed
                if(imageFrame.geometricBounds[3] - imageFrame.geometricBounds[1] < 
                   (doc.documentPreferences.pageWidth - insideMargin - outsideMargin)) {  // Use variables here
                    var currentX = imageFrame.geometricBounds[1];
                    var newX = insideMargin + 
                              ((doc.documentPreferences.pageWidth - insideMargin - outsideMargin) - 
                               (imageFrame.geometricBounds[3] - imageFrame.geometricBounds[1])) / 2;
                    imageFrame.move([newX - currentX, 0]);
                }
                
                yPosition = imageFrame.geometricBounds[2] + 0.5;
                // Explanation: The +0.5 is added to the yPosition to create a gap between the text frames.
            }
            
            currentType = null;
            currentSegment = [];
        }
        else if(currentType) {
            currentSegment.push(line);
        }
    }
    
    // Save the document
    var outputFile = new File("%OUTPUT_PATH%");
    doc.save(outputFile);
    // doc.close(); do not close indesign so that i can check immediately
    
    alert("Markdown converted successfully! ");
    
} catch(e) {
    alert("Error: " + e.message);
}
"""

    def convert(self, source, dest):
        if not source or not os.path.exists(source):
            logger.error("Invalid source file!")
            raise ValueError("Invalid source file!")
            
        if not dest:
            logger.error("Invalid destination file!")
            raise ValueError("Invalid destination file!")
            
        temp_dir = os.path.join(os.path.expanduser("~"), "Desktop", "EnneadTab_Markdown2Indesign")
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
        # Process markdown and prepare files
        segments_path = self._process_markdown(source, temp_dir)
        
        # Create and save JSX script
        script_path = self._prepare_jsx_script(segments_path, dest, temp_dir)
        
        # Execute script
        self._execute_jsx_script(script_path, temp_dir)
        
        # Debug inspections
        self.inspect_script_and_segments(script_path, segments_path)
        self.inspect_temp_dir(temp_dir)

        return True


    def _process_markdown(self, source, temp_dir):
        """Process markdown file into segments of text and images."""
        with open(source, 'r', encoding='utf-8') as f:
            md_content = f.read()
        
        segments = []
        current_text = []
        current_style = None  # Track current markdown style
        
        def flush_text():
            # Save accumulated text if any exists (with a theatrical flourish! 🎭)
            if current_text:
                # Strip those pesky newlines like a ninja removing unnecessary scrolls! 🥷
                text_content = ''.join(current_text).strip()
                segments.append(f"TEXT\n{text_content}\nENDTEXT")
                return []
            return current_text

        for line in md_content.split('\n'):
            # Check for image (our intermission act! 🎪)
            img_match = re.match(r'!\[(.*?)\]\((.*?)\)', line)
            if img_match:
                current_text = flush_text()
                img_path = img_match.group(2)
                if not os.path.isabs(img_path):
                    img_path = os.path.join(os.path.dirname(source), img_path)
                segments.append("IMAGE\n{}\nENDIMAGE".format(img_path.replace('\\', '/')))
                continue

            # Determine current line's style (costume change! 🎭)
            new_style = None
            if line.startswith('# '):
                new_style = 'h1'
            elif line.startswith('## '):
                new_style = 'h2'
            elif line.startswith('### '):
                new_style = 'h3'
            elif line.startswith('```'):
                new_style = 'code'
            else:
                new_style = 'body'

            # If style changes, start new segment (scene change! 🎬)
            if new_style != current_style and current_style is not None:
                current_text = flush_text()
            
            current_style = new_style
            current_text.append(line + '\n')
        
        # Don't forget the grand finale! 🎉
        if current_text:
            segments.append("TEXT\n{}\nENDTEXT".format(''.join(current_text)))
        
        # Save our masterpiece script
        segments_path = os.path.join(temp_dir, "segments.txt")
        with open(segments_path, 'w', encoding='utf-8') as f:

            f.write('\n'.join(segments))

            
        return segments_path

    def _prepare_jsx_script(self, segments_path, dest, temp_dir):
        """Prepare and save the JSX script."""
        script_content = self.indesign_script.replace(
            "%SEGMENTS_PATH%", segments_path.replace("\\", "/")
        ).replace(
            "%OUTPUT_PATH%", dest.replace("\\", "/")
        )
        
        script_path = os.path.join(temp_dir, "markdown_to_indesign.jsx")
        with open(script_path, 'w', encoding='utf-8', newline='\r\n') as f:
            f.write(script_content)
            
        return script_path

    def _execute_jsx_script(self, script_path, temp_dir):
        """Execute the JSX script using VBScript intermediary."""
        version = self.find_indesign_version_number()
        
        # Create VBScript
        vbs_content = f"""
        On Error Resume Next
        Set app = CreateObject("InDesign.Application.{version}")
        app.DoScript "{script_path}", 1246973031
        If Err.Number <> 0 Then
            WScript.Echo "Error: " & Err.Description
        End If
        """.format(version=version, script_path=script_path.replace("\\", "\\\\"))

        vbs_path = os.path.join(temp_dir, "run_markdown_script.vbs")
        with open(vbs_path, "w") as f:
            f.write(vbs_content)
        
        # Execute VBScript
        logger.info("🎭 Time for some InDesign magic...")
        result = subprocess.run(["cscript", "/nologo", vbs_path], 
                             capture_output=True, 
                             text=True)
        
        # Handle output and errors
        if result.stdout:
            logger.info(f"🎪 InDesign says: {result.stdout.strip()}")
        if result.stderr:
            logger.error(f"🎪 Oops! InDesign threw a tantrum: {result.stderr.strip()}")
            raise Exception(f"InDesign Script Error: {result.stderr.strip()}\nFull Error: {result.stderr}")

    def find_indesign_version_number(self):
        """Returns the latest available InDesign version by checking installation folders."""
        possible_versions = range(2030, 2015, -1)  # Check from newest to oldest
        
        for version in possible_versions:
            path = f"C:\\Program Files\\Adobe\\Adobe InDesign {version}\\InDesign.exe"
            if os.path.exists(path):
                logger.info(f"🎨 Found InDesign {version}! Let's make some magic!")
                return str(version)
        
        # If no version found, default to 2023
        logger.warning("🤔 Couldn't find InDesign! Using version 2023 and crossing fingers!")
        return "2023"

    def inspect_script_and_segments(self, script_path, segments_path):
        """Opens both script and segments in VS Code for inspection if available."""
        paths_to_open = [script_path, segments_path]
        try:
            logger.info("🔍 Opening files in VS Code for inspection...")
            # Try 'code' command first (VS Code in PATH)
            subprocess.run(["code", *paths_to_open], check=False)
        except FileNotFoundError:
            try:
                # Try common VS Code installation paths
                vscode_paths = [
                    r"C:\Users\{}\AppData\Local\Programs\Microsoft VS Code\Code.exe".format(os.getenv('USERNAME')),
                    r"C:\Program Files\Microsoft VS Code\Code.exe",
                    r"C:\Program Files (x86)\Microsoft VS Code\Code.exe"
                ]
                for vscode_path in vscode_paths:
                    if os.path.exists(vscode_path):
                        subprocess.run([vscode_path, *paths_to_open], check=False)
                        break
            except:
                logger.info("😅 Couldn't open VS Code, but the script ran anyway!")

    def inspect_temp_dir(self, temp_dir):
        """Opens the temporary directory for inspection."""
        logger.info(f"Temporary directory: {temp_dir}")
        logger.info(f"Directory exists: {os.path.exists(temp_dir)}")
        try:
            os.startfile(temp_dir)
        except:
            logger.warning("Could not open temporary directory for inspection")

if __name__ == "__main__":
    import datetime
    converter = MarkdownConverter()
    converter.convert(os.path.join(os.path.dirname(__file__), "test.md"),
                      os.path.join(os.path.dirname(__file__), f"output_{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.indd"))
