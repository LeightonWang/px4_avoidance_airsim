from PyQt5 import QtCore
from configparser import ConfigParser
from stable_baselines3 import TD3, SAC, PPO
import numpy as np
import gym_env
import gym
import math
import os
import sys
import cv2
from tqdm import tqdm
import time
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(CURRENT_DIR))
sys.path.append(
    r"C:\Users\helei\Documents\GitHub\UAV_Navigation_DRL_AirSim\scripts")


def rule_based_policy(obs):
    '''
    custom linear policy
    used for LGMD compare
    '''
    action = 0
    # 将obs从1~-1转换成0~1
    obs = np.squeeze(obs, axis=0)

    for i in range(5):
        obs[i] = obs[i]/2 + 0.5

    # obs_weight_depth = np.array([1.0, 3.0, 5.0, -3.0, -1.0, 3.0])
    obs_weight = np.array([1.0, 3.0, 3.0, -3.0, -1.0, 3.0])
    action = obs * obs_weight

    action_sum = np.sum(action)

    if action_sum > math.radians(40):
        action_sum = math.radians(40)
    elif action_sum < -math.radians(40):
        action_sum = -math.radians(40)

    return np.array([action_sum])


class EvaluateThread(QtCore.QThread):
    # signals
    def __init__(self, eval_path, config, model_file, eval_ep_num, eval_env=None, eval_dynamics=None):
        super(EvaluateThread, self).__init__()
        print("init training thread")

        # config
        self.cfg = ConfigParser()
        self.cfg.read(config)

        # change eval_env and eval_dynamics if is not None
        if eval_env is not None:
            self.cfg.set('options', 'env_name', eval_env)

        if eval_env == 'NH_center':
            self.cfg.set('environment', 'accept_radius', str(1))

        if eval_dynamics is not None:
            self.cfg.set('options', 'dynamic_name', eval_dynamics)


        self.env = gym.make('airsim-env-v0')
        self.env.set_config(self.cfg)

        self.eval_path = eval_path
        self.model_file = model_file
        self.eval_ep_num = eval_ep_num
        self.eval_env = self.cfg.get('options', 'env_name')
        self.eval_dynamics = self.cfg.get('options', 'dynamic_name')

    def terminate(self):
        print('Evaluation terminated')

    def run(self):
        # self.run_rule_policy()
        return self.run_drl_model()

    def run_drl_model(self):
        print('start evaluation')
        algo = self.cfg.get('options', 'algo')
        if algo == 'TD3':
            model = TD3.load(self.model_file, env=self.env)
        elif algo == 'SAC':
            model = SAC.load(self.model_file, env=self.env, device='cpu')
            # model.device = 'gpu'
        elif algo == 'PPO':
            model = PPO.load(self.model_file, env=self.env)
        else:
            raise Exception('algo set error {}'.format(algo))
        self.env.model = model

        obs = self.env.reset()
        episode_num = 0
        time_step = 0
        reward_sum = np.array([.0])
        episode_successes = []
        episode_crashes = []
        traj_list_all = []
        action_list_all = []
        state_list_all = []
        obs_list_all = []

        traj_list = []
        action_list = []
        state_raw_list = []
        step_num_list = []
        obs_list = []
        cv2.waitKey()

        while episode_num < self.eval_ep_num:
            t_start = time.time()
            unscaled_action, _ = model.predict(obs, deterministic=True)
            t_end = time.time()
            print('time: ', t_end - t_start)
            time_step += 1

            new_obs, reward, done, info, = self.env.step(unscaled_action)
            pose = self.env.dynamic_model.get_position()
            traj_list.append(pose)
            action_list.append(unscaled_action)
            state_raw_list.append(self.env.dynamic_model.state_raw)
            obs_list.append(obs)

            obs = new_obs
            reward_sum[-1] += reward

            if done:
                episode_num += 1
                maybe_is_success = info.get('is_success')
                maybe_is_crash = info.get('is_crash')
                print('episode: ', episode_num, ' reward:', reward_sum[-1],
                      'success:', maybe_is_success)
                episode_successes.append(float(maybe_is_success))
                episode_crashes.append(float(maybe_is_crash))
                reward_sum = np.append(reward_sum, .0)
                obs = self.env.reset()
                if info.get('is_success'):
                    traj_list.append(1)
                    action_list.append(1)
                    step_num_list.append(info.get('step_num'))
                elif info.get('is_crash'):
                    traj_list.append(2)
                    action_list.append(2)
                else:
                    traj_list.append(3)
                    action_list.append(3)
                # traj_list.append(info)
                traj_list_all.append(traj_list)
                action_list_all.append(action_list)
                state_list_all.append(state_raw_list)
                obs_list_all.append(obs_list)
                traj_list = []
                action_list = []
                state_raw_list = []
                obs_list = []

        # save trajectory data in eval folder
        eval_folder = self.eval_path + '/eval_{}_{}_{}'.format(self.eval_ep_num, self.eval_env, self.eval_dynamics)
        os.makedirs(eval_folder, exist_ok=True)
        np.save(eval_folder + '/traj_eval',
                np.array(traj_list_all, dtype=object))
        np.save(eval_folder + '/action_eval',
                np.array(action_list_all, dtype=object))
        np.save(eval_folder + '/state_eval',
                np.array(state_list_all, dtype=object))
        np.save(eval_folder + '/obs_eval',
                np.array(obs_list_all, dtype=object))

        print('Average episode reward: ', reward_sum[:self.eval_ep_num].mean(),
              'Success rate:', np.mean(episode_successes),
              'Crash rate: ', np.mean(episode_crashes),
              'average success step num: ', np.mean(step_num_list))
        
        results = [reward_sum[:self.eval_ep_num].mean(), np.mean(episode_successes), np.mean(episode_crashes), np.mean(step_num_list)]
        
        print(results)
        np.save(eval_folder + '/results', np.array(results))
        
        return results

    def run_rule_policy(self):
        obs = self.env.reset()
        episode_num = 0
        time_step = 0
        reward_sum = np.array([.0])
        while episode_num < self.eval_ep_num:
            unscaled_action = rule_based_policy(obs)
            time_step += 1
            new_obs, reward, done, info, = self.env.step(unscaled_action)
            reward_sum[-1] += reward

            obs = new_obs
            if done:
                episode_num += 1
                maybe_is_success = info.get('is_success')
                print('episode: ', episode_num, ' reward:', reward_sum[-1],
                      'success:', maybe_is_success)
                reward_sum = np.append(reward_sum, .0)
                obs = self.env.reset()


def main():
    eval_path = r'C:\Users\helei\Documents\GitHub\UAV_Navigation_DRL_AirSim\logs_eval\NH_center\nh-3d-sac\2022_12_06_11_25_SimpleMultirotor_mlp_SAC'
    config_file = eval_path + '/config/config.ini'
    model_file = eval_path + '/models/model_sb3.zip'
    # model_file = r'C:\Users\helei\Documents\GitHub\UAV_Navigation_DRL_AirSim\scripts\model_depth_5_good.zip'
    # config_file = r'C:\Users\helei\Documents\GitHub\UAV_Navigation_DRL_AirSim\configs_new\config_fixedwing.ini'
    eval_path = '.'

    eval_ep_num = 50
    evaluate_thread = EvaluateThread(eval_path, config_file, model_file,
                                     eval_ep_num)
    evaluate_thread.run()


def run_eval_multi():
    # run evaluation for multi models
    eval_logs_name = 'Trees'
    eval_logs_path = 'logs_eval/' + eval_logs_name
    eval_ep_num = 50
    eval_env_name = 'Trees'        # 1-Trees 2-SimpleAvoid 3-NH_center
    eval_dynamic_name = 'SimpleMultirotor'  # 1-SimpleMultirotor or Multirotor

    model_list = []
    for train_name in os.listdir(eval_logs_path):
        for repeat_name in os.listdir(eval_logs_path + '/' + train_name):
            model_path = eval_logs_path + '/' + train_name + '/' + repeat_name
            model_list.append(model_path)
            # print(model_path)

    # evaluate model according to model path
    eval_num = len(model_list)
    results_list = []

    for i in tqdm(range(eval_num)):
        eval_path = model_list[i]
        config_file = eval_path + '/config/config.ini'
        model_file = eval_path + '/models/model_sb3.zip'

        print(i, eval_path)
        evaluate_thread = EvaluateThread(eval_path, config_file, model_file, eval_ep_num, eval_env_name, eval_dynamic_name)
        results = evaluate_thread.run()
        results_list.append(results)

        del evaluate_thread

    # save all results in a numpy file
    print(results_list)
    np.save('logs_eval/results/eval_{}_{}_{}_{}'.format(eval_ep_num, eval_logs_name, eval_env_name, eval_dynamic_name), np.array(results_list))


if __name__ == "__main__":
    try:
        main()
        # run_eval_multi()
    except KeyboardInterrupt:
        print('system exit')
