from __future__ import division

from functools import partial
from multiprocessing import Pool
import logging

from six.moves import range
import numpy as np
import ollin

from ..core.utils import density_to_occupancy, logit
from .config import BASE_CONFIG


logger = logging.getLogger(__name__)


class OccupancyCalibrator(object):
    """Class to calibrate Occupancy parameters.

    This class also holds all data generated in calibration simulations.

    Attributes
    ----------
    config : :py:obj:`dict`
        Dictionary holding all configuration settings. See :py:mod:`.config` to
        see all relevant settings.
    movement_model : :py:obj:`.MovementModel`
        Reference to Movement model instance being calibrated.
    occupancy_info : :py:obj:`array`
        Numpy array of size::

            [num_home_ranges, num_niches, num_nums, num_worlds, trials]

        containing occupancy information. Here:

        :num_home_ranges:
            Refers to the number of simulated home ranges held in the
            configuration array ``config['home_ranges']``.
        :num_niches:
            Refers to the number of simulated niche sizes held in the
            configuration array ``config['niche_sizes']``.
        :num_nums:
            Refers to the number of different number of individuals
            simulated which are held in the configuration array
            ``config['nums`]``.
        :num_worlds:
            Refers to the number of sites created per selection of
            ``(home_range, niche_size)``.
        :trials:
            Refers to the number of simulations made per site.

        Hence if::

            oc = occupancy_info[i, j, k, l, m]

        this means that ``oc`` was the occupancy generated by
        ``config['nums'][k]`` individuals, randomly selected from the
        the m-th simulation at the l-th world generated with niche size
        ``config['niche_sizes'][j]`` and home range
        ``config['home_ranges'][k]``.

    """

    def __init__(self, movement_model, config=None):
        # Handle configurations
        if config is None:
            config = {}
        copy = BASE_CONFIG.copy()
        copy.update(config)
        self.config = copy

        # Point to movement model
        self.movement_model = movement_model

        # Calculate calibrations
        self.occupancy_info = self.calculate_oc_info()

    def calculate_oc_info(self):
        """Simulate multiple scenarios in parallel and record occupancy."""
        trials_per_world = self.config['trials_per_world']
        max_individuals = self.config['max_individuals']
        niche_sizes = self.config['niche_sizes']
        home_ranges = self.config['home_ranges']
        num_worlds = self.config['num_worlds']
        individuals = self.config['nums']
        season = self.config['season']
        range_ = self.config['range']

        model = self.movement_model

        num_niches = len(niche_sizes)
        num_home_ranges = len(home_ranges)
        num_densities = len(individuals)

        all_info = np.zeros([
            num_home_ranges,
            num_niches,
            num_densities,
            num_worlds,
            trials_per_world])
        arguments = [
            (home_range, niche_size)
            for home_range in home_ranges
            for niche_size in niche_sizes
            for k in range(num_worlds)]

        n_args = len(arguments)
        n_individuals = (
            num_home_ranges * num_niches *
            trials_per_world * np.sum(individuals))
        msg = 'Making {} runs of the simulator'
        msg += '\n\tSimulating a total of {} individuals'
        msg = msg.format(n_args, n_individuals)
        logger.info(msg)

        pool = Pool()
        try:
            results = pool.map_async(
                partial(
                    _get_single_oc_info,
                    model=model,
                    range_=range_,
                    season=season,
                    trials=trials_per_world,
                    max_individuals=max_individuals,
                    nums=individuals,
                ),
                arguments
            ).get(99999999999999)
            pool.close()
            pool.join()
        except KeyboardInterrupt:
            pool.terminate()
            raise KeyboardInterrupt

        logger.info('Simulations done.')

        arguments = [
            (i, j, k)
            for i in xrange(num_home_ranges)
            for j in xrange(num_niches)
            for k in xrange(num_worlds)]

        for (i, j, k), res in zip(arguments, results):
            all_info[i, j, :, k, :] = res

        return all_info

    def plot(
            self,
            figsize=(10, 10),
            ax=None,
            x_var='density',
            w_target=True,
            xscale=None,
            yscale=None,
            lwidth=0.1,
            wtext=False):
        """Plot graph of generated occupancy data and fit.

        Plots a grid of graphs of the relation between population density
        and resulting simulated occupancy. Adds a fitted line to the plot if
        desired to visually check calibration.

        Arguments
        ---------
        ax : :py:obj:`matplotlib.axes.Axes`, optional
            Ax in which to draw the plot. If not given a new one will be
            created.
        fisize : :py:obj:`tuple`, optional
            Size of figure to create. Used only if no ax is given.
        x_var : :py:obj:`str`, optional
            Variable to use in the x-axis. Options are: 'density',
            'home_range', 'niche_sizes'. Defaults to 'density'.
        w_target : :py:obj:`bool`, optional
            If True will plot a line fitted to velocity data. Defaults to True.
        xscale : :py:obj:`str`, optional
            Scale to use in the x-axis. Options are: 'linear', 'log'. Defaults
            to 'linear'.
        yscale : :py:obj:`str`, optional
            Scale to use in the y-axis. Options are: 'linear', 'log', 'logit'.
            Defaults to 'linear'.
        lwidth : :py:obj:`str`, optional
            Width of fitted line. Defaults to 0.1.
        wtext : :py:obj:`bool`, optional
            If True will add a text description to each plot, specifying the
            niche size and home_range.

        Returns
        -------
        ax : :py:obj:`matplotlib.axes.Axes`
            Ax object for further plotting.

        """
        import matplotlib.pyplot as plt
        from matplotlib.ticker import NullFormatter

        if ax is None:
            fig, ax = plt.subplots(figsize=figsize)

        home_ranges = np.array(self.config['home_ranges'])
        niche_sizes = np.array(self.config['niche_sizes'])
        nums = np.array(self.config['nums'])
        range_ = self.config['range']

        area = range_[0] * range_[1]
        density = nums / area
        hr_proportions = home_ranges / area

        if x_var == 'density':
            iterator1 = hr_proportions
            var2 = 'HRP'
            iterator2 = niche_sizes
            var3 = 'NS'
        elif x_var == 'home_range':
            iterator1 = density
            var2 = 'D'
            iterator2 = niche_sizes
            var3 = 'NS'
        elif x_var == 'niche_sizes':
            iterator1 = hr_proportions
            var2 = 'HRP'
            iterator2 = density
            var3 = 'D'

        ncols = len(iterator1)
        nrows = len(iterator2)

        params = self.movement_model.parameters['density']

        counter = 1
        for m, x in enumerate(iterator1):
            for n, y in enumerate(iterator2):
                nax = plt.subplot(nrows, ncols, counter)

                if x_var == 'density':
                    data = self.occupancy_info[m, n, :, :, :]
                    xcoords = density

                elif x_var == 'home_range':
                    data = self.occupancy_info[:, n, m, :, :]
                    xcoords = hr_proportions

                elif x_var == 'niche_sizes':
                    data = self.occupancy_info[m, :, n, :, :]
                    xcoords = self.niche_sizes

                mean = data.mean(axis=(1, 2))
                std = data.std(axis=(1, 2))
                uplim = mean + std
                dnlim = mean - std

                xtext = 0.1
                ytext = 0.8

                ylim0, ylim1 = -0.1, 1.1

                if xscale == 'log':
                    xcoords = np.log(xcoords)
                    xtext = np.log(xtext)

                if yscale == 'log':
                    mean = np.log(mean)
                    uplim = np.log(uplim)
                    dnlim = np.log(dnlim)
                    ylim0 = -6
                    ylim1 = 0
                    ytext = np.log(ytext)

                if yscale == 'logit':
                    mean = logit(mean)
                    uplim = logit(uplim)
                    dnlim = logit(dnlim)
                    ylim0 = -6
                    ylim1 = 4
                    ytext = logit(ytext)

                nax.plot(
                    xcoords,
                    mean,
                    linewidth=lwidth)
                nax.fill_between(
                    xcoords,
                    dnlim,
                    uplim,
                    alpha=0.6,
                    edgecolor='white')

                if w_target:
                    if x_var == 'density':
                        target = density_to_occupancy(
                            density,
                            x,
                            y,
                            parameters=params)
                    elif x_var == 'home_range':
                        target = density_to_occupancy(
                            x,
                            hr_proportions,
                            y,
                            parameters=params)
                    elif x_var == 'niche_sizes':
                        target = density_to_occupancy(
                            y,
                            x,
                            niche_sizes,
                            parameters=params)

                    if yscale == 'log':
                        target = np.log(target)
                    if yscale == 'logit':
                        target = logit(target)

                    nax.plot(
                        xcoords,
                        target,
                        color='red',
                        label='target')

                nax.set_ylim(ylim0, ylim1)
                nax.set_xlim(xcoords.min(), xcoords.max())

                if wtext:
                    nax.text(
                        xtext, ytext, '{}={}\n{}={}'.format(var2, x, var3, y))

                if m == ncols - 1:
                    nax.set_xlabel('{}={}'.format(var3, y))
                if n == 0:
                    nax.set_ylabel('{}={}'.format(var2, x))

                if m < ncols - 1:
                    nax.xaxis.set_major_formatter(NullFormatter())
                if n > 0:
                    nax.yaxis.set_major_formatter(NullFormatter())

                counter += 1
        plt.subplots_adjust(wspace=0, hspace=0)

        font = {'fontsize': 18}
        plt.figtext(0.4, 0.035, x_var, fontdict=font)
        plt.figtext(0.035, 0.5, "Occupancy (%)", fontdict=font, rotation=90)
        title = "Occupancy Calibration\n{}"
        title = title.format(self.movement_model.name)
        plt.figtext(0.38, 0.92, title, fontdict=font)
        return ax

    def fit(self):
        """Fit model parameters to simulated occupancy data.

        Returns
        -------
        fit : :py:obj:`dict`
            Dictionary holding the fitted parameters.

        """
        from sklearn.linear_model import LinearRegression
        home_ranges = np.array(self.config['home_ranges'])
        niche_sizes = np.array(self.config['niche_sizes'])
        nums = np.array(self.config['nums'])
        range_ = self.config['range']

        data = self.occupancy_info
        area = range_[0] * range_[1]
        density = nums / area
        hr_proportions = home_ranges / area

        X = []
        Y = []
        for i, nsz in enumerate(niche_sizes):
            for j, hr in enumerate(hr_proportions):
                for k, dens in enumerate(density):
                    oc_data = data[j, i, k, :, :].ravel()
                    hr_data = hr * np.ones_like(oc_data)
                    dens_data = dens * np.ones_like(oc_data)
                    nsz_data = nsz * np.ones_like(oc_data)
                    Y.append(logit(oc_data))
                    X.append(
                        np.stack([np.log(hr_data),
                                  np.log(dens_data),
                                  np.log(nsz_data)], -1))
        X = np.concatenate(X, 0)
        Y = np.concatenate(Y, 0)

        lrm = LinearRegression()
        lrm.fit(X, Y)

        alpha = lrm.intercept_
        hr_exp = lrm.coef_[0]
        den_exp = lrm.coef_[1]
        nsz_exp = lrm.coef_[2]

        parameters = {
            'alpha': alpha,
            'hr_exp': hr_exp,
            'density_exp': den_exp,
            'niche_size_exp': nsz_exp}
        return parameters


def _get_single_oc_info(
        args,
        model,
        range_,
        season,
        trials,
        max_individuals,
        nums):
    home_range, niche_size = args

    site = ollin.Site.make_random(niche_size, range=range_)
    mov = ollin.Movement.simulate(
        site,
        num=max_individuals,
        home_range=home_range,
        days=season,
        movement_model=model)

    n_nums = len(nums)
    results = np.zeros([n_nums, trials])

    for n, num in enumerate(nums):
        for k in range(trials):
            submov = mov.sample(num)
            oc = ollin.Occupancy(submov)
            results[n, k] = oc.occupancy

    return results
