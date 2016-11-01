import os
import shutil

import autoencoder.autoencoder as autoencoder
from utilities.start_tensorboard import start_tensorboard


from utilities.flags import FLAGS, home_out


_data_dir = FLAGS.data_dir
_summary_dir = FLAGS.summary_dir
_chkpt_dir = FLAGS.chkpt_dir


def _check_and_clean_dir(d):
  if os.path.exists(d):
    shutil.rmtree(d)
  os.mkdir(d)


def main():
  home = home_out('')
  if not os.path.exists(home):
    os.makedirs(home)
  if not os.path.exists(_data_dir):
    os.mkdir(_data_dir)

  _check_and_clean_dir(_summary_dir)
  _check_and_clean_dir(_chkpt_dir)

  os.mkdir(os.path.join(_chkpt_dir, '1'))
  os.mkdir(os.path.join(_chkpt_dir, '2'))
  os.mkdir(os.path.join(_chkpt_dir, '3'))
  os.mkdir(os.path.join(_chkpt_dir, 'fine_tuning'))

  start_tensorboard()

  ae = autoencoder.main_unsupervised()
  autoencoder.main_supervised(ae)

if __name__ == '__main__':
    main()

