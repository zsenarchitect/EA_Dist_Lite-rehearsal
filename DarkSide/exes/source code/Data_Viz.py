import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import webbrowser
import _Exe_Util

class InteractiveVisualizer:
    def __init__(self):
        self.fig = None
        self.save_and_open_chart()

    def create_chart(self):
        print("Creating chart...")
        self.fig = make_subplots(rows=1, cols=1)
        self.fig.add_trace(
            go.Scatter(
                x=self.data[self.x_axis_title],
                y=self.data[self.y_axis_title],
                mode='markers+text',
                name='Data Points',
                marker=dict(size=8),
                text=self.data[self.primary_value_title],
                textposition='top center',
                customdata=self.data.values,
                hovertemplate=self.generate_hover_template()
            )
        )
        self.fig.update_layout(
            title=self.title,
            legend_title="Click to filter",
            xaxis_title=self.x_axis_title if self.show_axis_title else None,
            yaxis_title=self.y_axis_title if self.show_axis_title else None,
            xaxis = dict(showticklabels=self.show_axis_increment),
            yaxis = dict(showticklabels=self.show_axis_increment),
            hovermode='closest',
            dragmode='drawline',
            newshape=dict(line_color='cyan')
        )

    def generate_hover_template(self):
        return "<br>".join([f"{col}: %{{customdata[{i}]}}" for i, col in enumerate(self.data.columns)])

    def update_data(self, new_data):
        self.data = new_data
        self.create_chart()

    def save_and_open_chart(self):
        data = _Exe_Util.get_data("interactive_chart_data")
        self.title = data.get('title', 'Interactive Data Visualization')
        self.x_axis_title = data.get('x_axis_title', None)
        self.y_axis_title = data.get('y_axis_title', None)
        self.primary_value_title = data.get('primary_value_title', None)
        self.show_axis_title = data.get('show_axis_title', True)
        self.show_axis_increment = data.get('show_axis_increment', True)
        
        raw_data = data.get('data', [])
        flattened_data = [
            {**item, **item.get('attributes', {})} for item in raw_data
        ]
        pd_data = pd.DataFrame(flattened_data)
        self.update_data(pd_data)

 

        html_file = _Exe_Util.get_file_in_dump_folder('{}.html'.format(self.title))
        self.fig.write_html(html_file)
        webbrowser.open_new_tab(html_file)

# Example usage
if __name__ == "__main__":
    InteractiveVisualizer()
