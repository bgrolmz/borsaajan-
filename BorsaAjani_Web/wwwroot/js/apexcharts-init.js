// ApexCharts initialization for Blazor Server
let chartInstance = null;

// New function: Render from JSON string
window.renderCandlestickChartFromJson = (chartDataJson, symbol) => {
    console.log('renderCandlestickChartFromJson called', { 
        chartDataJsonLength: chartDataJson?.length || 0, 
        symbol: symbol,
        chartDataJsonPreview: chartDataJson?.substring(0, 200)
    });

    let candlestickData;
    try {
        candlestickData = JSON.parse(chartDataJson);
        console.log('JSON parsed successfully, data length:', candlestickData?.length);
        console.log('First data point:', candlestickData?.[0]);
    } catch (e) {
        console.error('Failed to parse chart data JSON:', e);
        console.error('JSON string:', chartDataJson?.substring(0, 500));
        return;
    }

    if (chartInstance) {
        chartInstance.destroy();
        chartInstance = null;
    }

    const chartElement = document.getElementById('candlestick-chart');
    if (!chartElement) {
        console.error('Chart element not found!');
        return;
    }

    console.log('Chart element found, creating chart...');

    if (!candlestickData || candlestickData.length === 0) {
        console.error('No candlestick data provided!');
        return;
    }

    const options = {
        series: [
            {
                name: 'Price',
                type: 'candlestick',
                data: candlestickData
            }
        ],
        chart: {
            type: 'candlestick',
            height: 500,
            toolbar: {
                show: true,
                tools: {
                    zoom: true,
                    zoomin: true,
                    zoomout: true,
                    pan: true,
                    reset: true
                }
            },
            zoom: {
                enabled: true,
                type: 'x'
            }
        },
        theme: {
            mode: 'dark',
            palette: 'palette1'
        },
        plotOptions: {
            candlestick: {
                colors: {
                    upward: '#3fb950',
                    downward: '#f85149'
                }
            }
        },
        xaxis: {
            type: 'datetime',
            labels: {
                style: {
                    colors: '#c9d1d9',
                    fontSize: '12px'
                },
                datetimeUTC: false,
                format: 'dd MMM',
                rotate: 0,
                rotateAlways: false,
                showDuplicates: false
            },
            title: {
                text: 'Tarih',
                style: {
                    color: '#c9d1d9',
                    fontSize: '13px',
                    fontWeight: 600
                }
            }
        },
        yaxis: {
            title: {
                text: 'Fiyat ($)',
                style: {
                    color: '#c9d1d9',
                    fontSize: '13px',
                    fontWeight: 600
                }
            },
            labels: {
                style: {
                    colors: '#c9d1d9',
                    fontSize: '12px'
                },
                formatter: function (val) {
                    return '$' + val.toFixed(2);
                }
            }
        },
        tooltip: {
            theme: 'dark',
            x: {
                format: 'dd MMM yyyy'
            }
        },
        grid: {
            borderColor: '#30363d',
            strokeDashArray: 4
        },
        colors: ['#3fb950']
    };

    console.log('Creating ApexCharts instance with options:', {
        seriesCount: options.series.length,
        dataPoints: candlestickData.length,
        chartType: options.chart.type
    });

    try {
        if (typeof ApexCharts === 'undefined') {
            console.error('ApexCharts is not loaded!');
            return;
        }
        
        chartInstance = new ApexCharts(chartElement, options);
        console.log('ApexCharts instance created, rendering...');
        
        chartInstance.render().then(() => {
            console.log('Chart rendered successfully!');
            console.log('Chart element dimensions:', {
                width: chartElement.offsetWidth,
                height: chartElement.offsetHeight
            });
        }).catch((error) => {
            console.error('Chart render error:', error);
            console.error('Error stack:', error.stack);
        });
    } catch (error) {
        console.error('Failed to create ApexCharts instance:', error);
        console.error('Error stack:', error.stack);
        console.error('ApexCharts available:', typeof ApexCharts !== 'undefined');
    }
};

window.destroyChart = () => {
    if (chartInstance) {
        chartInstance.destroy();
        chartInstance = null;
    }
};

window.checkElementExists = (elementId) => {
    return document.getElementById(elementId) !== null;
};

window.checkApexChartsLoaded = () => {
    return typeof ApexCharts !== 'undefined';
};

// Legacy function: Render from object array (for backward compatibility)
window.renderCandlestickChart = (candlestickData, volumeData, symbol) => {
    console.log('renderCandlestickChart called (legacy)', { 
        candlestickDataLength: candlestickData?.length || 0, 
        symbol: symbol 
    });

    if (chartInstance) {
        chartInstance.destroy();
        chartInstance = null;
    }

    const chartElement = document.getElementById('candlestick-chart');
    if (!chartElement) {
        console.error('Chart element not found!');
        return;
    }

    console.log('Chart element found, creating chart...');

    if (!candlestickData || candlestickData.length === 0) {
        console.error('No candlestick data provided!');
        return;
    }

    const options = {
        series: [
            {
                name: 'Price',
                type: 'candlestick',
                data: candlestickData
            }
        ],
        chart: {
            type: 'candlestick',
            height: 500,
            toolbar: {
                show: true,
                tools: {
                    zoom: true,
                    zoomin: true,
                    zoomout: true,
                    pan: true,
                    reset: true
                }
            },
            zoom: {
                enabled: true,
                type: 'x'
            }
        },
        theme: {
            mode: 'dark',
            palette: 'palette1'
        },
        plotOptions: {
            candlestick: {
                colors: {
                    upward: '#3fb950',
                    downward: '#f85149'
                }
            }
        },
        xaxis: {
            type: 'datetime',
            labels: {
                style: {
                    colors: '#c9d1d9',
                    fontSize: '12px'
                },
                datetimeUTC: false,
                format: 'dd MMM',
                rotate: 0,
                rotateAlways: false,
                showDuplicates: false
            },
            title: {
                text: 'Tarih',
                style: {
                    color: '#c9d1d9',
                    fontSize: '13px',
                    fontWeight: 600
                }
            }
        },
        yaxis: {
            title: {
                text: 'Fiyat ($)',
                style: {
                    color: '#c9d1d9',
                    fontSize: '13px',
                    fontWeight: 600
                }
            },
            labels: {
                style: {
                    colors: '#c9d1d9',
                    fontSize: '12px'
                },
                formatter: function (val) {
                    return '$' + val.toFixed(2);
                }
            }
        },
        tooltip: {
            theme: 'dark',
            x: {
                format: 'dd MMM yyyy'
            }
        },
        grid: {
            borderColor: '#30363d',
            strokeDashArray: 4
        },
        colors: ['#3fb950']
    };

    try {
        chartInstance = new ApexCharts(chartElement, options);
        chartInstance.render().then(() => {
            console.log('Chart rendered successfully');
        }).catch((error) => {
            console.error('Chart render error:', error);
            console.error('Error stack:', error.stack);
        });
    } catch (error) {
        console.error('Failed to create ApexCharts instance:', error);
        console.error('Error stack:', error.stack);
    }
};
