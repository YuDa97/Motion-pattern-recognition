'''
实验前提：采集数据时手机x轴与重力方向垂直

1.Model
参数列表（4个参数）：
线性加速度矩阵（x轴加速度、y轴加速度、z轴加速度）；
重力加速度矩阵（x轴重力加速度、y轴重力加速度、z轴重力加速度）;
四元数矩阵（四元数x、四元数y、四元数z、四元数w）
fuse_yaw为matlab使用互补滤波或者EKF滤波获得的航向角。
min_acc：pdr最小加速度阈值，不同数据集min_acc不同。
2.Model参数类型：
numpy.ndarray
'''

import math
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import norm
from matplotlib import rcParams
from mpl_toolkits.mplot3d import Axes3D

plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False

class Model(object):
    def __init__(self, linear, gravity, rotation,fuse_yaw=None,min_acc=0.4):
        self.linear = linear
        self.gravity = gravity
        self.rotation = rotation
        self.fuse_yaw = fuse_yaw
        self.min_acc = min_acc
    '''
        四元数转化为欧拉角
    '''
    def quaternion2euler(self):
        rotation = self.rotation
        x = rotation[:, 0]
        y = rotation[:, 1]
        z = rotation[:, 2]
        w = rotation[:, 3]
        pitch = np.arcsin(2*(w*y-z*x))
        roll = np.arctan2(2*(w*x+y*z),1-2*(x*x+y*y))
        yaw = np.arctan2(2*(w*z+x*y),1-2*(z*z+y*y))
        return pitch, roll, yaw
    
    def coordinate_conversion(self):
        '''
        获得手机坐标系与地球坐标系之间的角度（theta）
        '''
        gravity = self.gravity
        linear = self.linear

        # g_x = gravity[:, 0]
        g_y = gravity[:, 1]
        g_z = gravity[:, 2]

        # linear_x = linear[:, 0]
        linear_y = linear[:, 1]
        linear_z = linear[:, 2]
        
        theta = np.arctan(np.abs(g_z/g_y))

        # 得到垂直方向加速度（除去g）
        a_vertical = linear_y*np.cos(theta) + linear_z*np.sin(theta)

        return a_vertical
    

    def step_counter(self, frequency=25, walkType='normal', **kw):
        '''
        步数检测函数

        walkType取值:
        normal: 正常行走模式
        abnormal: 融合定位行走模式（每一步行走间隔大于1s）

        返回值：
        steps
        字典型数组,每个字典保存了峰值位置(index)与该点的合加速度值(acceleration)
        '''
        offset = 1.1
        g = 0.96
        a_vertical = self.coordinate_conversion()
        slide = int(frequency * offset) # 滑动窗口长度
    
        # 行人加速度阈值
        min_acceleration = self.min_acc * g 
        max_acceleration = 5 * g   # 5g
        valley_acceleration = -1 #谷值阈值
        valleyWin_scale = 37 # 谷值窗口宽度
        # 峰值间隔(s)
        min_interval = 0.4 if walkType=='normal' else 2 # 'abnormal
        # max_interval = 1
        # 计算步数
        steps = []
        peak = {'index': 0, 'acceleration': 0, \
                'v_index': 0, 'v_acceleration': 0, \
                'm_pattern': -2} # v_index：谷值索引，v_acceleration：谷值, m_pattern: 运动模式
        # 以宽度为slide的滑动窗检测谷值，选择在峰值后加窗
        # 条件1：峰值在min_acceleration~max_acceleration之间
        for i, v in enumerate(a_vertical):
            if v >= peak['acceleration'] and v >= min_acceleration and v <= max_acceleration:
                peak['acceleration'] = v
                peak['index'] = i
            if i%slide == 0 and peak['index'] != 0:
                valleyWin_start = peak['index'] 
                valleyWin = a_vertical[valleyWin_start:valleyWin_start+valleyWin_scale]
                peak['v_acceleration'] = np.min(valleyWin)
                peak['v_index'] = int(np.argwhere(valleyWin == np.min(valleyWin))[0]) + valleyWin_start
                if 'motionPattern' in kw:
                    pattern_index = int(i/kw['motionPatternWindowWide'])
                    peak['m_pattern'] = kw['motionPattern'][pattern_index]
                steps.append(peak)
                peak = {'index': 0, 'acceleration': 0, 'v_index': 0, 'v_acceleration': 0, 'm_pattern': -2}
        
        # 条件2：两个峰值之前间隔至少大于0.4s*frequency
        # del使用的时候，一般采用先记录再删除的原则
        if len(steps)>0:
            lastStep = steps[0]
            dirty_points = []
            for key, step_dict in enumerate(steps):
                # print(step_dict['index'])
                if key == 0:
                    continue
                if step_dict['index']-lastStep['index'] < min_interval*frequency:
                    # print('last:', lastStep['index'], 'this:', step_dict['index'])
                    if step_dict['acceleration'] <= lastStep['acceleration']:#如果当前峰值小于上一峰值
                        dirty_points.append(key)#删去当前峰值
                    else:
                        lastStep = step_dict
                        dirty_points.append(key-1)
                else:
                    lastStep = step_dict
                #删去谷值大于谷值阈值的峰，该算法出现漏检
                #if step_dict['v_acceleration'] > valley_acceleration:
                #    dirty_points.append(key)
            
            counter = 0 # 记录删除数量，作为偏差值，删除以后下标会移动
            for key in dirty_points:
                del steps[key-counter]
                counter = counter + 1
        
        return steps
    
    # 步长推算
    # k为身高相关常数
    def step_stride(self, max_acceleration, min_acceleration, k=0.37):
        return np.power(max_acceleration - min_acceleration, 1/4) * k

    # 航向角
    # 根据姿势直接使用yaw
    def step_heading(self):
        _, _, yaw = self.quaternion2euler()
        # init_theta = yaw[0] # 初始角度
        for i,v in enumerate(yaw):
            # yaw[i] = -(v-init_theta)
            yaw[i] = -v # 由于yaw逆时针为正向，转化为顺时针为正向更符合常规的思维方式
        return yaw
    
    '''
        步行轨迹的每一个相对坐标位置
        返回的是预测作为坐标
        bias为人为建立参考系与北东天参考系的偏差（在物理楼六楼参考系下，偏差为18度左右）
    '''
    def pdr_position(self, frequency=25, walkType='normal', \
                    offset = 0,initPosition=(0, 0, 0), bias = 18*np.pi/180, \
                    fuse_oritation = False, **kw):
        if fuse_oritation is True:
            yaw = self.fuse_yaw
        else:
            yaw = self.step_heading()
        set = 1.1 # 与step_counter函数保持一致
        slide = frequency * set
        if 'predictPattern' in kw:
            steps = self.step_counter(frequency=frequency, walkType=walkType, \
                                    motionPatternWindowWide=kw['m_WindowWide'], motionPattern=kw['predictPattern'])
        else:
            steps = self.step_counter(frequency=frequency, walkType=walkType)
        position_x = []
        position_y = []
        position_z = []
        x = initPosition[0]
        y = initPosition[1]
        z = initPosition[2]
        position_x.append(x)
        position_y.append(y)
        position_z.append(z)
        strides = []#记录步长
        angle = [offset]
        nums = len(steps)
        for i in range(nums):
            v = steps[i]
            index = v['index']
            pattern = v['m_pattern']
            # 获取航向角
            yaw_range = yaw[int(index-slide):int(index+slide)]
            theta = np.mean(yaw_range) + bias 
            angle.append(theta)
            if pattern == 1: # 若为行走
                length = self.step_stride(v['acceleration'], v['v_acceleration'], k=0.37)
                length = round(length/0.6, 2)
                strides.append(length)
                if len(angle) >= 2:
                    if np.abs(angle[-1] - angle[-2])*180/np.pi < 4:
                        angle[-1] = angle[-2]
                x = x + length*np.sin(angle[-1])
                y = y + length*np.cos(angle[-1])
                position_x.append(x)
                position_y.append(y)
                position_z.append(z)
            elif pattern == 3: # 若为下楼
                length = 0.5
                strides.append(length)
                if len(angle) >= 2:
                    if np.abs(angle[-1] - angle[-2])*180/np.pi < 4:
                        angle[-1] = angle[-2]
                x = x + length*np.sin(angle[-1])
                y = y + length*np.cos(angle[-1])
                z = z - 0.25
                position_x.append(x)
                position_y.append(y)
                position_z.append(z)
            elif pattern == 2: # 若为上楼
                length = 0.5
                strides.append(length)
                if len(angle) >= 2:
                    if np.abs(angle[-1] - angle[-2])*180/np.pi < 4:
                        angle[-1] = angle[-2]
                x = x + length*np.sin(angle[-1])
                y = y + length*np.cos(angle[-1])
                z = z + 0.25
                position_x.append(x)
                position_y.append(y)
                position_z.append(z)
            else: # 静止
                strides.append(0)
                x = x
                y = y
                z = z
                position_x.append(x)
                position_y.append(y)
                position_z.append(z)
        # 步长计入一个状态中，最后一个位置没有下一步，因此步长记为0
        return position_x, position_y, position_z, strides + [0], angle


    def show_steps(self, frequency=25, walkType='normal'):
        '''
        显示步伐检测图像
        walkType取值:
        - normal:正常行走模式
        - abnormal:融合定位行走模式(每一步行走间隔大于1s)
        '''
        a_vertical = self.coordinate_conversion()
        steps = self.step_counter(frequency=frequency, walkType=walkType)

        index_test = []
        value_test = []
        index_valley = []
        value_valley = []
        for v in steps:
            index_test.append(v['index'])
            value_test.append(v['acceleration'])
            index_valley.append(v['v_index'])
            value_valley.append(v['v_acceleration'])
        
        config = {
            "font.family":'Times New Roman',  # 设置字体类型
        #     "mathtext.fontset":'stix',
        }
        rcParams.update(config)
        textstr = '='.join(('steps', str(len(steps))))
        _, ax = plt.subplots(figsize=(15,8))
        props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)
        ax.text(0.05, 0.95, textstr, transform=ax.transAxes, fontsize=20,
            verticalalignment='top', bbox=props)
        plt.plot(a_vertical)
        plt.scatter(index_test, value_test, color='r')
        plt.scatter(index_valley, value_valley, color='k', marker='^')
        plt.xlabel('samples', fontsize=20)
        plt.ylabel('Vertical Acceleration', fontsize=20)
        plt.xticks(fontsize=18) #设置坐标轴刻度大小
        plt.yticks(fontsize=18)
        plt.show()
        # plt.savefig('D:/硕士论文/图表/PDR竖直加速度.jpg',format='jpg',bbox_inches = 'tight',dpi=300)

    '''
        输出一个数据分布散点图, 用来判断某一类型数据的噪声分布情况, 通常都会是高斯分布, 
    '''
    def show_gaussian(self, data, fit):
        wipe = 150
        data = data[wipe:len(data)-wipe]
        division = 100
        acc_min = np.min(data)
        acc_max = np.max(data)
        interval = (acc_max-acc_min)/division
        counter = [0]*division
        index = []

        for k in range(division):
            index.append(acc_min+k*interval)

        for v in data:
            for k in range(division):
                if v>=(acc_min+k*interval) and v<(acc_min+(k+1)*interval):
                    counter[k] = counter[k]+1
        
        textstr = '\n'.join((
            r'$max=%.3f$' % (acc_max, ),
            r'$min=%.3f$' % (acc_min, ),
            r'$mean=%.3f$' % (np.mean(data), )))
        _, ax = plt.subplots()
        props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)
        ax.text(0.05, 0.95, textstr, transform=ax.transAxes, fontsize=14,
            verticalalignment='top', bbox=props)
        plt.scatter(index, counter, label='distribution')

        if fit==True:
            length = math.ceil((acc_max-acc_min)/interval)
            counterArr = length * [0]
            for value in data:
                key = int((value - acc_min) / interval)
                if key >=0 and key <length:
                    counterArr[key] += 1
            normal_mean = np.mean(data)
            normal_sigma = np.std(data)
            normal_x = np.linspace(acc_min, acc_max, 100)
            normal_y = norm.pdf(normal_x, normal_mean, normal_sigma)
            normal_y = normal_y * np.max(counterArr) / np.max(normal_y)
            ax.plot(normal_x, normal_y, 'r-', label='fitting')

        plt.xlabel('acceleration')
        plt.ylabel('total samples')
        plt.legend()
        plt.show()

    def show_data(self, dataType):
        
        '''
        显示三轴加速度的变化情况
        '''
        if dataType=='linear':
            linear = self.linear
            x = linear[:,0]
            y = linear[:,1]
            z = linear[:,2]
            index = range(len(x))
            
            ax1 = plt.subplot(3,1,1) #第一行第一列图形
            ax2 = plt.subplot(3,1,2) #第一行第二列图形
            ax3 = plt.subplot(3,1,3) #第二行
            plt.sca(ax1)
            plt.title('x')
            plt.scatter(index,x)
            plt.sca(ax2)
            plt.title('y')
            plt.scatter(index,y)
            plt.sca(ax3)
            plt.title('z')
            plt.scatter(index,z)
            plt.show()
        elif dataType=='gravity':
            gravity = self.gravity
            x = gravity[:,0]
            y = gravity[:,1]
            z = gravity[:,2]
            index = range(len(x))
            
            ax1 = plt.subplot(3,1,1) #第一行第一列图形
            ax2 = plt.subplot(3,1,2) #第一行第二列图形
            ax3 = plt.subplot(3,1,3) #第二行
            plt.sca(ax1)
            plt.title('x')
            plt.scatter(index,x)
            plt.sca(ax2)
            plt.title('y')
            plt.scatter(index,y)
            plt.sca(ax3)
            plt.title('z')
            plt.scatter(index,z)
            plt.show()
        else: # rotation
            rotation = self.rotation
            x = rotation[:,0]
            y = rotation[:,1]
            z = rotation[:,2]
            w = rotation[:,3]
            index = range(len(x))
            
            ax1 = plt.subplot(4,1,1) #第一行第一列图形
            ax2 = plt.subplot(4,1,2) #第一行第二列图形
            ax3 = plt.subplot(4,1,3) #第二行
            ax4 = plt.subplot(4,1,4) #第二行
            plt.sca(ax1)
            plt.title('x')
            plt.scatter(index,x)
            plt.sca(ax2)
            plt.title('y')
            plt.scatter(index,y)
            plt.sca(ax3)
            plt.title('z')
            plt.scatter(index,z)
            plt.sca(ax4)
            plt.title('w')
            plt.scatter(index,w)
            plt.show()

    def show_trace(self, frequency=25, walkType='normal', initPosition=(0, 0, 0), **kw):
        '''
        显示PDR运动轨迹图
        '''
        from matplotlib import rcParams
        config = {
            "font.family":'Times New Roman',  # 设置字体类型
            #     "mathtext.fontset":'stix',
                }
        rcParams.update(config)
        fig = plt.figure()
        ax = fig.gca(projection='3d')
        plt.grid()
        handles = []
        labels = []

        if 'real_trace' in kw:
            real_trace = kw['real_trace'].T
            trace_x = real_trace[0]
            trace_y = real_trace[1]
            trace_z = real_trace[2]
            l1, = ax.plot(trace_x, trace_y, trace_z, color='g')
            handles.append(l1)
            labels.append('Real tracks')
            plt.scatter(trace_x, trace_y, trace_z, color='orange')
            #for k in range(0, len(trace_x)):
            #    plt.annotate(k, xy=(trace_x[k], trace_y[k]), xytext=(trace_x[k]+0.1,trace_y[k]+0.1), color='green')#在各个点旁边添加步数记录

        if 'offset' in kw:
            offset = kw['offset']
        else:
            offset = 0
        
        x, y, z, _, _ = self.pdr_position(frequency=25, walkType='normal', \
                    offset = 0,initPosition=(0, 0, 0), bias = 18*np.pi/180, \
                    fuse_oritation = False, \
                    predictPattern=kw['predictPattern'], m_WindowWide=kw['m_WindowWide'])
        print('steps:', len(x)-1)

        #for k in range(0, len(x)):
        #    plt.annotate(k, xy=(x[k], y[k]), xytext=(x[k]+0.1,y[k]+0.1))
        l2, = ax.plot(x, y, z, 'o-')
        handles.append(l2)
        ax.set_xlabel('X', fontsize=18)#设置横纵坐标标签
        ax.set_ylabel('Y', fontsize=18)
        ax.set_zlabel('Z', fontsize=18)
        labels.append('PDR positioning')
        plt.legend(handles=handles,labels=labels,loc='best',fontsize = 20)
        ax.tick_params(labelsize=14) #设置坐标轴刻度大小
        plt.show()
        #plt.savefig('E:/动态定位/PDR+WIFI+EKF/location-master/Figures/raw_pdr.jpg',bbox_inches = 'tight')
        