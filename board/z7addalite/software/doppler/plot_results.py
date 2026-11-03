"""Plot recorded synthetic test results; never fabricate or acquire RF data."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    data=json.loads(args.results.read_text(encoding='utf-8'))
    args.out.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.sans-serif':['Microsoft YaHei','SimHei','DejaVu Sans'],
                         'axes.unicode_minus':False,'font.size':10,'svg.fonttype':'path',
                         'axes.spines.top':False,'axes.spines.right':False})
    modes=['uncompensated_reference','prediction_only','legacy_measurement','hybrid']
    names=['不补偿参考','仅预测','原有逐块测量','预测＋测量']
    colors=['#a4adb6','#e3a049','#4774bb','#168c83']
    cases=['static_bias','ramp_bias','smooth_bias','acquisition_stress','chirp_stress']
    labels=['固定偏差','缓慢斜坡','平滑变化','48 kHz 捕获压力','快速变化率压力']
    lookup={(r['scenario'],r['mode']):r for r in data['summary']}
    fig,axes=plt.subplots(2,1,figsize=(11,7),gridspec_kw={'height_ratios':[3,1.5]},layout='constrained')
    for j,mode in enumerate(modes):
        axes[0].bar(np.arange(5)+(j-1.5)*.18,[lookup[c,mode]['rms_hz'] for c in cases],
                    width=.17,color=colors[j],label=names[j])
    axes[0].set_yscale('log');axes[0].set_ylim(.05,150000)
    axes[0].set_xticks(np.arange(5),labels);axes[0].set_ylabel('补偿后残余频偏 RMS / Hz（对数轴）')
    axes[0].grid(axis='y',alpha=.18);axes[0].set_axisbelow(True)
    axes[0].legend(ncol=4,loc='upper center',frameon=False)
    passes=np.array([[lookup[c,m]['crc_pass'] for c in cases] for m in modes])
    axes[1].imshow(passes,vmin=0,vmax=8,cmap='GnBu',aspect='auto')
    axes[1].set_xticks(np.arange(5),labels);axes[1].set_yticks(np.arange(4),names)
    for row in range(4):
        for col in range(5):
            axes[1].text(col,row,f'{passes[row,col]}/8',ha='center',va='center',
                         color='white' if passes[row,col]>4 else '#263845',fontweight='bold')
    axes[1].set_title('CRC 通过且指令内容逐字节一致的帧数',fontsize=10)
    fig.suptitle('测控接收补偿对照 · 主机合成 ADC 波形',fontsize=15,fontweight='bold')
    fig.supxlabel('带模型偏差和噪声的独立信号源；压力用例不是实际轨道工况；未进行实板射频验证',fontsize=9)
    for ext in ('png','svg'):fig.savefig(args.out/f'doppler_comparison.{ext}',dpi=220)
    plt.close(fig)

    rows=data['tracking'];t=np.array([r['capture_ms']/1000 for r in rows])
    truth=np.array([r['truth_hz'] for r in rows]);pred=np.array([r['predicted_hz'] for r in rows])
    req=np.array([r['requested_cfo_hz'] for r in rows])
    measured=np.array([r['measured_cfo_hz'] if r['crc_ok'] else np.nan for r in rows])
    fig,axes=plt.subplots(3,1,figsize=(11,8),sharex=True,layout='constrained',
                          gridspec_kw={'height_ratios':[2,2,1]})
    axes[0].plot(t,truth,color='#263845',label='独立注入真值（仅评分）')
    axes[0].plot(t,pred,'--',color=colors[2],label='预测频偏')
    axes[0].plot(t,req,color=colors[1],label='预测＋历史残差（搜索中心）')
    axes[0].plot(t,measured,'.',color=colors[3],label='CRC 有效的当前块测量')
    axes[0].set_ylabel('原始接收频偏 / Hz');axes[0].legend(ncol=2,fontsize=9,frameon=False)
    axes[1].plot(t,truth-pred,'--',color=colors[2],label='仅预测残差')
    axes[1].plot(t,truth-req,color=colors[1],label='跨块预测残差')
    axes[1].plot(t,truth-measured,'o-',color=colors[3],markersize=3,label='当前块精细补偿残差')
    axes[1].set_ylabel('频偏误差 / Hz');axes[1].legend(ncol=3,fontsize=9,frameon=False)
    axes[2].step(t,[r['state'] for r in rows],where='post',color=colors[3])
    axes[2].set_yticks([1,3,4],['仅预测','混合','保持']);axes[2].set_ylim(.5,4.5)
    axes[2].set_ylabel('采样开始时状态');axes[2].set_xlabel('同一仿真时钟 / s')
    for ax in axes:
        ax.axvspan(t[7]-.2,t[11]+.2,color='#dce3e8',alpha=.65,zorder=-1)
        ax.grid(alpha=.15);ax.set_xlim(t[0],t[-1])
    axes[0].text(t[7],pred[7]+10,'5 次采样仅噪声',color='#566773',fontsize=9)
    fig.suptitle('跨采样跟踪与观测丢失退化 · 主机仿真',fontsize=15,fontweight='bold')
    fig.supxlabel('24 个采样块：19 个真实解码观测、5 个噪声块；无效观测不会训练残差滤波器',fontsize=9)
    for ext in ('png','svg'):fig.savefig(args.out/f'doppler_tracking.{ext}',dpi=220)
    plt.close(fig)


if __name__=='__main__':main()
