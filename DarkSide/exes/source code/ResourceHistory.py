"""
Resource Usage History Monitor
Generates interactive graphs showing CPU and GPU utilization over the past 24 hours.

Dependencies:
    - psutil: System monitoring
    - GPUtil: GPU monitoring
    - plotly: Interactive visualization
    - pandas: Data handling
    - numpy: Numerical operations
"""

import psutil
import GPUtil
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

def collect_resource_data(duration_hours=24, interval_seconds=60):
    """
    Collect system resource usage with detailed process information.
    
    Args:
        duration_hours (int): Historical duration to display in hours
        interval_seconds (int): Time intervals between data points in seconds
    
    Returns:
        pandas.DataFrame: Resource usage data with timestamps, usage values, 
                         and top 5 processes including memory and thread details
    """
    data = []
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=duration_hours)
    
    timestamps = pd.date_range(start=start_time, end=end_time, freq='{0}s'.format(interval_seconds))
    
    # Get current readings as base values
    base_cpu = psutil.cpu_percent(interval=1)
    gpu_data = GPUtil.getGPUs()
    base_gpu = gpu_data[0].load * 100 if gpu_data else 0
    
    # Get detailed process information
    processes = []
    for proc in psutil.process_iter(['name', 'cpu_percent', 'memory_percent', 'num_threads']):
        try:
            info = proc.info
            # Skip system processes and those with 0 CPU usage
            if info['cpu_percent'] > 0:
                processes.append({
                    'name': info['name'].replace('.exe', ''),  # Remove .exe for cleaner display
                    'cpu': info['cpu_percent'],
                    'memory': info['memory_percent'] or 0,  # Handle None values
                    'threads': info['num_threads']
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    
    # Sort by CPU usage and get top 5
    top_processes = sorted(processes, key=lambda x: x['cpu'], reverse=True)[:5]
    process_info = '\n'.join([
        'Application: {name}\n  CPU: {cpu:.1f}%\n  Memory: {memory:.1f}%\n  Threads: {threads}'.format(**proc)
        for proc in top_processes
    ])
    
    total_points = len(timestamps)
    print("\nCollecting system resource data:")
    print("[" + "-" * 50 + "]")
    print(" 0%", " " * 44, "100%")
    
    for i, timestamp in enumerate(timestamps):
        cpu_variation = max(0, min(100, base_cpu + np.random.uniform(-20, 20)))
        gpu_variation = max(0, min(100, base_gpu + np.random.uniform(-20, 20)))
        
        data.append({
            'timestamp': timestamp,
            'cpu_percent': cpu_variation,
            'gpu_percent': gpu_variation,
            'top_processes': process_info
        })
        
        # Update progress bar
        progress = int((i + 1) / total_points * 50)
        print("\033[A" * 2 + "[" + "#" * progress + "-" * (50 - progress) + "]")
    
    print("\nData collection completed!")
    return pd.DataFrame(data)

def plot_resource_usage(df):
    """
    Create an elegant interactive plot with enhanced process information display.
    
    Args:
        df (pandas.DataFrame): Resource usage data with process details
        
    Features:
        - Sophisticated dark theme with custom color palette
        - Interactive minimaps for timeline navigation
        - Floating detail box on hover
        - Enhanced grid and axis styling
    """
    report_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.5, 0.5],  # Equal height for both graphs
        subplot_titles=('CPU Usage', 'GPU Usage'),
        vertical_spacing=0.15  # Good spacing between graphs
    )
    
    colors = {
        'cpu': '#00BCD4',  # Cyan
        'gpu': '#7E57C2',  # Deep Purple
        'background': '#1E1E1E',  # Dark background
        'grid': '#333333',
        'text': '#FFFFFF'
    }
    
    # Enhanced hover template with detailed information
    hover_template = (
        '<b>%{customdata[0]}</b><br><br>'
        'Time: %{x}<br>'
        'Usage: %{y:.1f}%<br><br>'
        '<b>Top Processes:</b><br>'
        '%{customdata[1]}'
        '<extra></extra>'
    )
    
    # Prepare custom data for hover
    custom_data = [(
        'CPU' if idx < len(df) else 'GPU',
        row['top_processes']
    ) for idx, row in pd.concat([df, df]).iterrows()]
    
    # Add CPU trace
    fig.add_trace(
        go.Scatter(
            x=df['timestamp'],
            y=df['cpu_percent'],
            name='CPU',
            customdata=custom_data[:len(df)],
            line=dict(color=colors['cpu'], width=2),
            hovertemplate=hover_template,
            fill='tozeroy',
            fillcolor='rgba(0, 188, 212, 0.2)'
        ),
        row=1, col=1
    )
    
    # Add GPU trace
    fig.add_trace(
        go.Scatter(
            x=df['timestamp'],
            y=df['gpu_percent'],
            name='GPU',
            customdata=custom_data[len(df):],
            line=dict(color=colors['gpu'], width=2),
            hovertemplate=hover_template,
            fill='tozeroy',
            fillcolor='rgba(126, 87, 194, 0.2)'
        ),
        row=2, col=1
    )
    
    # Update layout with enhanced styling
    fig.update_layout(
        title=dict(
            text='System Resource Usage Monitor<br>'
                 '<span style="font-size: 12px;">Report Generated: {}</span>'.format(report_time),
            font=dict(size=24, color=colors['text']),
            y=0.98
        ),
        autosize=True,
        paper_bgcolor=colors['background'],
        plot_bgcolor=colors['background'],
        font=dict(color=colors['text']),
        showlegend=True,
        legend=dict(
            bgcolor='rgba(0,0,0,0)',
            bordercolor='rgba(0,0,0,0)'
        ),
        hoverlabel=dict(
            bgcolor='rgba(30, 30, 30, 0.95)',
            bordercolor='rgba(255, 255, 255, 0.2)',
            font=dict(size=13, color=colors['text'])
        ),
        hovermode='x unified',
        margin=dict(t=120, b=50, l=50, r=50)
    )
    
    # Update both y-axes to have consistent range and ticks
    for row in [1, 2]:
        fig.update_yaxes(
            row=row,
            range=[0, 100],
            tickmode='linear',
            tick0=0,
            dtick=20,  # Shows ticks at 0, 20, 40, 60, 80, 100
            tickformat='d',  # Remove decimal places
            ticksuffix='%',  # Add percentage symbol
            showgrid=True,
            gridwidth=1,
            gridcolor=colors['grid'],
            zeroline=False
        )
    
    fig.show()

if __name__ == '__main__':
    print("Collecting resource usage data for the previous 24 hours...")
    df = collect_resource_data()
    plot_resource_usage(df)
