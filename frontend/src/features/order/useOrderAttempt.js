import { useCallback, useEffect, useRef, useState } from 'react';
import { useSelector } from 'react-redux';

import { fingerprintOrderPayload } from './cart.js';
import { orderApi } from './api.js';
import { attemptFailureMessage, progressMessage } from './orderMessages.js';
import {
  createOrderWithRetry,
  queryOrderAttemptOnce,
  resumeOrderAttempt,
} from './orderRetry.js';
import { pendingOrderStorage } from './pendingOrderStorage.js';

const EMPTY_ATTEMPT = { fingerprint: '', key: '' };

function failureFromResult(result) {
  const expired = result.status === 'expired';
  const code = expired
    ? 'ORDER_ATTEMPT_EXPIRED'
    : result.error?.code || result.failureCode || 'ORDER_CREATE_FAILED';
  return {
    code,
    message: expired
      ? '这次下单请求已经过期，请重新提交。'
      : result.error?.message || attemptFailureMessage(result.failureCode),
    requestId: result.error?.requestId || null,
    fieldErrors: result.error?.fieldErrors || [],
  };
}

/**
 * 管理订单提交的幂等键、重试和跨刷新恢复。
 * 只有服务端明确返回成功订单时才发布 succeededOrder；未知结果始终保留。
 */
export function useOrderAttempt() {
  const userId = useSelector((state) => state.auth.user?.user_id);
  // 服务端结果明确前保留原请求，阻止用户用新幂等键重复创建订单。
  const [pendingAttempt, setPendingAttempt] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [progress, setProgress] = useState('');
  const [failure, setFailure] = useState(null);
  const [unknownMessage, setUnknownMessage] = useState('');
  const [isUnknownNoticeOpen, setIsUnknownNoticeOpen] = useState(false);
  const [succeededOrder, setSucceededOrder] = useState(null);
  // 相同订单内容复用同一幂等键；同步 ref 同时防止快速双击的状态竞争。
  const idempotencyRef = useRef(EMPTY_ATTEMPT);
  const submittingRef = useRef(false);

  const clearAttempt = useCallback(
    (attemptKey) => {
      pendingOrderStorage.clear(userId, attemptKey);
      idempotencyRef.current = EMPTY_ATTEMPT;
      setPendingAttempt((current) =>
        !current || current.key === attemptKey ? null : current,
      );
    },
    [userId],
  );

  const showUnknownResult = useCallback((message) => {
    setProgress('');
    setUnknownMessage(message);
    setIsUnknownNoticeOpen(true);
  }, []);

  const applyAttemptResult = useCallback(
    (result, attempt) => {
      // 缺少订单号的“成功”响应不能触发跳转，应继续按未知结果处理。
      if (result.status === 'succeeded' && result.order?.order_id) {
        clearAttempt(attempt.key);
        setProgress('');
        setFailure(null);
        setIsUnknownNoticeOpen(false);
        setSucceededOrder(result.order);
        return result;
      }

      if (result.status === 'failed' || result.status === 'expired') {
        clearAttempt(attempt.key);
        setProgress('');
        setIsUnknownNoticeOpen(false);
        setFailure(failureFromResult(result));
        return result;
      }

      showUnknownResult(
        '订单结果暂时无法确认，请选择重试确认或退出并稍后确认。',
      );
      return { ...result, status: 'unknown' };
    },
    [clearAttempt, showUnknownResult],
  );

  const submitAttempt = useCallback(
    async (attempt, resume) => {
      if (!userId || submittingRef.current) {
        return { status: 'blocked' };
      }

      submittingRef.current = true;
      setIsSubmitting(true);
      setFailure(null);
      setIsUnknownNoticeOpen(false);
      setProgress('正在提交订单……');

      try {
        const execute = resume ? resumeOrderAttempt : createOrderWithRetry;
        const result = await execute({
          payload: attempt.payload,
          idempotencyKey: attempt.key,
          api: orderApi,
          onProgress: (nextProgress) => {
            setProgress(progressMessage(nextProgress));
          },
        });
        return applyAttemptResult(result, attempt);
      } catch {
        showUnknownResult(
          '订单确认过程发生异常，操作已经保存，请重试确认或稍后处理。',
        );
        return { status: 'unknown' };
      } finally {
        submittingRef.current = false;
        setIsSubmitting(false);
      }
    },
    [applyAttemptResult, showUnknownResult, userId],
  );

  const submitOrder = useCallback(
    async (payload) => {
      if (!userId) {
        return {
          status: 'blocked',
          error: { message: '登录状态异常，请重新登录后再提交订单' },
        };
      }

      const fingerprint = fingerprintOrderPayload(payload);
      if (pendingAttempt) {
        const pendingFingerprint = fingerprintOrderPayload(
          pendingAttempt.payload,
        );
        if (pendingFingerprint !== fingerprint) {
          return {
            status: 'blocked',
            error: {
              message: '上次下单结果仍未确认，请先处理上次请求。',
            },
          };
        }
        return submitAttempt(pendingAttempt, true);
      }

      if (idempotencyRef.current.fingerprint !== fingerprint) {
        idempotencyRef.current = {
          fingerprint,
          key: `web-${crypto.randomUUID()}`,
          createdAt: new Date().toISOString(),
          payload,
        };
      }

      const nextAttempt = idempotencyRef.current;
      // 请求发出前先持久化；即使页面立即关闭，也能恢复同一个幂等操作。
      pendingOrderStorage.set(userId, nextAttempt);
      setPendingAttempt(nextAttempt);
      return submitAttempt(nextAttempt, false);
    },
    [pendingAttempt, submitAttempt, userId],
  );

  const continuePendingOrder = useCallback(async () => {
    if (!pendingAttempt) return { status: 'blocked' };
    return submitAttempt(pendingAttempt, true);
  }, [pendingAttempt, submitAttempt]);

  const dismissUnknownNotice = useCallback(() => {
    setIsUnknownNoticeOpen(false);
  }, []);

  const clearSucceededOrder = useCallback(() => {
    setSucceededOrder(null);
  }, []);

  useEffect(() => {
    if (!userId) return undefined;
    const storedAttempt = pendingOrderStorage.get(userId);
    if (!storedAttempt) return undefined;

    idempotencyRef.current = storedAttempt;
    setPendingAttempt(storedAttempt);
    let active = true;

    queryOrderAttemptOnce({
      idempotencyKey: storedAttempt.key,
      api: orderApi,
    }).then(({ attempt, error }) => {
      if (!active) return;
      if (error) {
        showUnknownResult(
          '暂时无法确认上次下单结果，操作仍已保存。',
        );
        return;
      }
      if (attempt?.status === 'succeeded' && attempt.order) {
        applyAttemptResult(
          { status: 'succeeded', order: attempt.order },
          storedAttempt,
        );
        return;
      }
      if (attempt?.status === 'failed' || attempt?.status === 'expired') {
        applyAttemptResult(
          {
            status: attempt.status,
            failureCode: attempt.failure_code,
          },
          storedAttempt,
        );
        return;
      }
      showUnknownResult(
        attempt?.status === 'not_found'
          ? '上次请求尚未到达服务端，可以使用原操作安全重试。'
          : '上次订单仍在处理中，请重试确认或退出并稍后确认。',
      );
    });

    return () => {
      active = false;
    };
  }, [applyAttemptResult, showUnknownResult, userId]);

  useEffect(() => {
    if (!failure) return undefined;
    const failureToClear = failure;
    const timer = globalThis.setTimeout(() => {
      setFailure((current) => (current === failureToClear ? null : current));
    }, 3000);
    return () => globalThis.clearTimeout(timer);
  }, [failure]);

  return {
    pendingAttempt,
    isSubmitting,
    progress,
    failure,
    unknownMessage,
    isUnknownNoticeOpen,
    succeededOrder,
    submitOrder,
    continuePendingOrder,
    dismissUnknownNotice,
    clearSucceededOrder,
  };
}
