from __future__ import print_function
from multiprocessing import Pool

import sys
import numpy as np
import pycamtrap as pc


RANGE = 20
TRIALS_PER_WORLD = 100
NUM_WORLDS = 10
VELOCITIES = np.linspace(0.1, 3, 10)
NICHE_SIZES = np.linspace(0.3, 0.9, 6)


class VelocityCalibrator(object):
    def __init__(
            self,
            movement_model,
            velocities=VELOCITIES,
            niche_sizes=NICHE_SIZES,
            trials_per_world=TRIALS_PER_WORLD,
            num_worlds=NUM_WORLDS,
            range=RANGE):

        self.movement_model = movement_model
        self.velocities = velocities
        self.niche_sizes = niche_sizes
        self.trials_per_world = trials_per_world
        self.num_worlds = num_worlds
        self.range = range

        self.velocity_info = self.calculate_velocity_info()

    def calculate_velocity_info(self):
        n_vel = len(self.velocities)
        n_nsz = len(self.niche_sizes)
        num = self.trials_per_world
        mov = self.movement_model

        all_info = np.zeros(
            [n_vel, n_nsz, self.num_worlds, self.trials_per_world])
        arguments = [
            Info(mov, vel, nsz, num, self.range)
            for vel in self.velocities
            for nsz in self.niche_sizes
            for k in xrange(self.num_worlds)]

        print('Simulating {} scenarios'.format(len(arguments)))
        pool = Pool()
        try:
            results = pool.map(get_single_velocity_info, arguments)
            pool.close()
            pool.join()
        except KeyboardInterrupt:
            pool.terminate()
            sys.exit()
            quit()

        arguments = [
            (i, j, k)
            for i in xrange(n_vel)
            for j in xrange(n_nsz)
            for k in xrange(self.num_worlds)]

        for (i, j, k), res in zip(arguments, results):
            all_info[i, j, k, :] = res

        return all_info

    def plot(self, cmap='Set2', figsize=(10, 10), ax=None):
        import matplotlib.pyplot as plt
        from matplotlib.cm import get_cmap

        if ax is None:
            fig, ax = plt.subplots(figsize=figsize)
        cmap = get_cmap(cmap)

        for n, nsz in enumerate(self.niche_sizes):
            color = cmap(float(n) / len(self.niche_sizes))
            data = self.velocity_info[:, n, :, :]
            mean = data.mean(axis=(1, 2))
            std = data.std(axis=(1, 2))

            ax.plot(
                self.velocities,
                mean,
                c=color,
                label='Niche Size: {}'.format(nsz))
            ax.fill_between(
                self.velocities,
                mean - std,
                mean + std,
                color=color,
                alpha=0.6,
                edgecolor='white')

        ax.plot(self.velocities, self.velocities, color='red', label='target')
        ax.set_title('Velocity Calibration')

        ax.set_xlabel('target velocity (Km/day)')
        ax.set_ylabel('calculated velocity (Km/day)')

        ax.set_xticks(self.velocities)
        ax.set_yticks(self.velocities)

        ax.legend()
        return ax

    def fit(self):
        from sklearn.linear_model import LinearRegression

        coefficients = np.zeros(len(self.niche_sizes))
        for num, niche_size in enumerate(self.niche_sizes):
            data = self.velocity_info[:, num, :, :]
            concat = []

            for k, vel in enumerate(self.velocities):
                vdata = data[k, :, :].ravel()
                vdata = np.stack([vel * np.ones_like(vdata), vdata], -1)
                concat.append(vdata)

            data = np.concatenate(concat, 0)
            Y, X = data.T
            model = LinearRegression(fit_intercept=False)
            model.fit(X[:, None], Y[:, None])
            coefficients[num] = model.coef_[0, 0]

        return coefficients


class Info(object):
    __slots__ = [
        'movement_model',
        'velocity',
        'niche_size',
        'num',
        'range']

    def __init__(
            self,
            movement_model,
            velocity,
            niche_size,
            num,
            range_):
        self.movement_model = movement_model
        self.velocity = velocity
        self.niche_size = niche_size
        self.num = num
        self.range = range_


def get_single_velocity_info(info):
    init = pc.InitialCondition(info.niche_size, range=info.range)
    mov = pc.MovementData.simulate(
        init,
        num=info.num,
        velocity=info.velocity,
        days=info.movement_model.parameters['hr_days'],
        movement_model=info.movement_model)
    analyzer = pc.MovementAnalyzer(mov)
    return analyzer.velocities.mean(axis=1)
