__title__ = "StackPSD"
__doc__ = """Stack PSD Files Tool

Automates the process of stacking and combining PSD files for rendering workflows.
Features:
- Processes glass and chrome version renderings
- Creates layered PSD compositions with proper blend modes
- Handles special camera views (cam 13, cam 17) with background templates
- Exports final compositions as high-quality JPG files
- Supports multiple study variations (angled_frame, sawtooth, solar_panel, etc.)

Workflow:
1. Prepares data by matching glass/chrome version pairs
2. Processes each pair through Photoshop automation
3. Applies appropriate blend modes and adjustments
4. Saves as PSD and exports as JPG for presentation"""
import process_data as pd
import prepare_miro as pm

if __name__ == '__main__':
    for _ in range(1):
        print (_)
        pd.main()
        pm.main()
    print('done')
    pass
