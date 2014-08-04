"""
The interface subpackage provides View and Plot types to wrap
external objects with. Currently only a Pandas compatibility wrapper
is provided, which allows integrating Pandas DataFrames within the
DataViews compositioning and animation framework. Additionally, it
provides methods to apply operations to the underlying data and
convert it to standard DataViews View types.
"""

from collections import defaultdict, OrderedDict

import numpy as np
import pandas
from matplotlib import pyplot as plt

import param

from . import Dimension
from .dataviews import HeatMap, DataStack, Table, TableStack
from .plots import Plot
from .options import options, PlotOpts
from .views import View, Stack


class DFrameView(View):
    """
    DFrameView provides a convenient compatibility wrapper around Pandas
    DataFrames.  It provides several core functions:

        * Allows integrating several Pandas plot types with the
          DataViews plotting system (includes plot, boxplot, histogram
          and scatter_matrix).

        * Allows conversion of the Pandas DataFrames to different View
          types, including Tables and HeatMaps.

        * Provides several convenient wrapper methods to apply
          DataFrame methods and slice data. This includes:

              1) The apply method, which takes the DataFrame method to
                 be applied as the first argument and passes any
                 supplied args or kwargs along.

              2) The select and __getitem__ method which allow for
                 selecting and slicing the data using NdMapping.          
    """

    value = param.ClassSelector(class_=(str, Dimension), precedence=-1)

    def __init__(self, data, **params):
        if not isinstance(data, pandas.DataFrame):
            raise Exception('DataFrame View type requires Pandas dataframe as data.')
        super(DFrameView, self).__init__(data, **params)


    def __getitem__(self, key):
        if key is ():
            return self
        else:
            if len(key) == self.ndims:
                return self.select(**dict(zip(self.dimension_labels, key)))
            else:
                raise KeyError(key)


    def select(self, **select):
        df = self.data
        for dim, k in select.items():
            if isinstance(k, slice):
                df = df[(k.start < df[dim]) & (df[dim] < k.stop)]
            else:
                df = df[df[dim] == k]
        return self.clone(df)
        

    def apply(self, name, *args, **kwargs):
        """
        Applies the Pandas dframe method corresponding to the supplied
        name with the supplied args and kwargs.
        """
        return self.clone(getattr(self.data, name)(*args, **kwargs))


    def dframe(self):
        """
        Returns a copy of the internal dframe.
        """
        return self.data.copy()


    def dfstack(self, dimensions=[]):
        """
        Splits the supplied dimensions out into a DFrameStack.
        """
        stack = DFrameStack(None, dimensions=dimensions)
        view_dims = set(self.dimension_labels) - set(dimensions)
        for k, v in self.data.groupby(dimensions):
            stack[k] = self.clone(v.filter(view_dims),
                                  dimensions=[self.dim_dict[d] for d in view_dims])
        return stack


    def _create_table(self, temp_dict, value_dim, dims):
        params = dict(value=value_dim, dimensions=[self.dim_dict.get(d, d) for d in dims]) if dims else {}
        return Table(temp_dict, label=self.label, **params)


    def _create_heatmap(self, temp_dict, value_dim, dims):
        return HeatMap(temp_dict, label=self.label, dimensions=[self.dim_dict.get(d, d) for d in dims],
                       value=self.dim_dict[value_dim])


    def _export_dataview(self, value_dim='', indices=[], reduce_fn=None, view_dims=[], stack_dims=[], view_method=None, stack_type=None):
        """
        The core conversion method from the Pandas DataFrame to a View
        or Stack type. The value_dim specifies the column in the
        DataFrame to select, additionally indices or a reduce_fn can
        be supplied to select or reduce multiple entries in the
        DataFrame. Further, the view_dims and stack_dims determine
        which Dimension will be grouped and supplied to the appropriate
        view_method and stack_type respectively.
        """

        # User error checking
        selected_dims = [value_dim]+view_dims+stack_dims
        for dim in selected_dims:
            if dim not in self.dimension_labels:
                raise Exception("DFrameView has no Dimension %s." % dim)

        # Filtering out unselected dimensions
        filter_dims = list(set(self.dimension_labels) - set(selected_dims))        
        df = self.data.filter(selected_dims) if filter_dims else self.dframe()

        # Set up for View and Stack dimension splitting operations
        view_dimensions = view_dims
        if stack_dims:
            stack_dfs = df.groupby(stack_dims)
            stack = stack_type(None, dimensions=[self.dim_dict[d] for d in stack_dims])
        else:
            stack_dfs = [(None, df)]
            stack = {}

        # Iterating over stack elements
        for stack_key, stack_group in stack_dfs:
            # Apply reduction function
            if reduce_fn:
                # Find indices for value and View dimensions
                cols = list(stack_group.columns)
                val_idx = cols.index(value_dim)
                vdim_inds = [cols.index(d) for d in view_dims]

                # Iterate over rows and collate the result.
                temp_dict = defaultdict(list)
                for row in stack_group.values:
                    if view_dims:
                        key = tuple((row[ind] for ind in vdim_inds))
                    else:
                        key = value_dim
                    temp_dict[key].append(row[val_idx])
                temp_dict = {k:reduce_fn(v) for k, v in temp_dict.items()}
            # Select values using by indices
            else:
                temp_dict = OrderedDict()
                # If the selected dimensions values are not unique add Index
                if not len(indices) == 1:
                    indices = indices if indices else list(stack_group.index)
                    view_dimensions = ['Index'] + view_dims
                
                # Get data from the DataFrame
                for ind in indices:
                    key = tuple([stack_group.loc[ind, d] for d in view_dims])
                    if not len(indices) == 1: 
                        key = (ind,) + key
                    key = key if len(key) > 1 else key[0]
                    temp_dict[key] = stack_group.loc[ind, value_dim]
            stack[stack_key] = view_method(temp_dict, value_dim, view_dimensions)
        if stack_dims:
            return stack
        else:
            return stack[None]


    def table(self, value_dim, indices=[], reduce_fn=None, dims=[], stack_dims=[]):
        """
        Conversion method from DataFrame to DataViews table. Requires
        a value_dimension to be specified. Optionally a list indices
        or a reduce_fn can be specified to select or reduce multiple
        entries. Finally view_dims and stack_dims can be specified to
        be inserted into the Table and TableStack respectively.  If
        not stack_dims are specified a single Table will be returned.
        """
        return self._export_dataview(value_dim, indices, reduce_fn, dims, stack_dims, self._create_table, TableStack)


    def heatmap(self, value_dim, dims, index=None, reduce_fn=None, stack_dims=[]):
        """
        Conversion method from DataFrame to DataViews
        HeatMap. Requires a value_dim, the HeatMap dims and either a
        single index or a reduce_fn, to ensure there's only one value
        returned. Optionally stack_dims can be specified to stack the
        HeatMap over.
        """
        indices = [index] if index else []
        if 1 > len(dims) > 2:
            raise Exception("HeatMap supports either one or two dimensions")
        return self._export_dataview(value_dim, indices, reduce_fn, dims, stack_dims, self._create_heatmap, DataStack)



class DFrameStack(Stack):

    data_type = DFrameView

    def dfview(self):
        dframe = self.dframe()
        return self.last.clone(dframe, dimensions=self.dimensions+list(dframe.columns))
    


class classproperty(object):
    def __init__(self, f):
        self.f = f
    def __get__(self, obj, owner):
        return self.f(owner)



class DFramePlot(Plot):
    """
    DFramePlot provides a wrapper around Pandas dataframe plots.
    It takes a single DFrameView or DFrameStack as input and plots it using
    the plotting command selected via the plot_type.

    The plot_options specifies the valid options to be supplied
    to the selected plot_type via options.style_opts.
    """

    plot_type = param.ObjectSelector(default='boxplot', objects=['plot', 'boxplot',
                                                                 'hist', 'scatter_matrix'],
                                     doc="""Selects which Pandas plot type to use.""")

    plot_options = {'plot':            ['kind', 'stacked', 'xerr',
                                        'yerr', 'share_x', 'share_y',
                                        'table', 'style',
                                        'secondary_y', 'legend',
                                        'logx', 'logy', 'position',
                                        'colormap', 'mark_right'],
                    'hist':            ['column', 'by', 'grid',
                                        'xlabelsize', 'xrot',
                                        'ylabelsize', 'yrot',
                                        'sharex', 'sharey', 'hist',
                                        'layout'],
                    'boxplot':         ['column', 'by', 'fontsize',
                                        'layout', 'grid', 'rot'],
                    'scatter_matrix':  ['alpha', 'grid', 'diagonal',
                                        'marker', 'range_padding',
                                        'hist_kwds', 'density_kwds'],
                    'autocorrelation': ['kwds']}

    @classproperty
    def style_opts(cls):
        opt_set = set()
        for opts in cls.plot_options.values():
            opt_set |= set(opts)
        return list(opt_set)

    _stack_type = DFrameStack


    def __init__(self, dfview, zorder=0, **kwargs):
        self._stack = self._check_stack(dfview, DFrameView)
        super(DFramePlot, self).__init__(zorder, **kwargs)


    def __call__(self, axis=None, cyclic_index=0, lbrt=None):
        dfview = self._stack.last
        composed = axis is not None

        if composed and self.plot_type == 'scatter_matrix':
            raise Exception("Scatter Matrix plots can't be composed.")
        elif composed and len(dfview.dimensions) > 1 and self.plot_type in ['hist']:
            raise Exception("Multiple %s plots cannot be composed." % self.plot_type)

        title = None if self.zorder > 0 else self._format_title(-1)
        self.ax = self._axis(axis, title)

        # Process styles
        self.style = View.options.style(dfview)[cyclic_index]
        styles = self.style.keys()
        for k in styles:
            if k not in self.plot_options[self.plot_type]:
                self.warning('Plot option %s does not apply to %s plot type.' % (k, self.plot_type))
                self.style.pop(k)
        self.style['figsize'] = self.size
        
        # Legacy fix for Pandas, can be removed for Pandas >0.14
        if self.plot_type == 'boxplot':
            self.style['return_type'] = 'axes'

        self._update_plot(dfview)

        if not axis:
            fig = self.handles.get('fig', plt.gcf())
            plt.close(fig)
        return self.ax if axis else self.handles.get('fig', plt.gcf())


    def _update_plot(self, dfview):
        import pandas
        if self.plot_type == 'scatter_matrix':
            pandas.scatter_matrix(dfview.data, ax=self.ax, **self.style)
        else:
            getattr(dfview.data, self.plot_type)(ax=self.ax, **self.style)


    def update_frame(self, n, lbrt=None):
        """
        Update the plot for an animation.
        """
        n = n if n < len(self) else len(self) - 1
        dfview = list(self._stack.values())[n]
        if not self.plot_type in ['hist', 'scatter_matrix']:
            self.ax.cla()
            self.handles['title'] = self.ax.set_title('')
            self._update_title(n)
        self._update_plot(dfview)
        plt.draw()


Plot.defaults.update({DFrameView: DFramePlot})

options.DFView = PlotOpts()
