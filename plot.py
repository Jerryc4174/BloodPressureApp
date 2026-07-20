import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from sklearn.linear_model import LinearRegression

def plot_data(df) -> Figure:
    df.columns = df.columns.str.strip()
    df['Date'] = pd.to_datetime(df['Date'])
    df.sort_values('Date', inplace=True, ascending=True)
    # Pre-calculate ordinal once
    df['date_ordinal'] = df['Date'].map(pd.Timestamp.toordinal)

    metrics = ['Upper', 'Lower', 'BPM']
    
    # Create a figure with 3 subplots stacked vertically
    fig, axes = plt.subplots(3, 1, figsize=(10, 12), sharex=True)
    
    for i, metric in enumerate(metrics):
        ax = axes[i]
        
        # Regression
        X = df[['date_ordinal']]
        y = df[metric]
        model = LinearRegression().fit(X, y)
        trend = model.predict(X)
        
        # Plotting
        ax.plot(df['Date'], df[metric], marker='o', linestyle='-', label=metric)
        ax.plot(df['Date'], trend, linestyle='--', color='r', label='Trend')
        
        # Formatting
        ax.set_title(f'{metric} Over Time')
        ax.set_ylabel(metric)
        ax.grid(True)
        ax.legend(loc='upper left')

    # Format the bottom X-axis
    axes[2].xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=8))
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter('%d/%m/%Y'))
    axes[2].tick_params(axis='x', labelrotation=45)
    for label in axes[2].get_xticklabels():
        label.set_horizontalalignment('right')
    
    fig.autofmt_xdate(rotation=45, ha='right')
    plt.tight_layout()
    return fig